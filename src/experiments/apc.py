"""検証D：APC 補正による異常の隠蔽（理想化した補正モデル）。

モデル（Wafer ごとの補正。Alignment と Overlay は別の計測なので、補正に使う点と評価に使う点を分ける）
- 潜在的な面内傾向 f(s)（正常 + 異常）を、Alignment マップ A と Overlay 検証マップ O でそれぞれ測る（誤差は独立）。
- 補正：Alignment 計測値 a に d_c 次の XY 多項式を最小二乗で当てはめ、係数 ĉ を補正量とする（d_c = 1 は線形6パラメータ）。
- 補正後の Overlay 残差 r = (f_O + ε_O) − X_O ĉ（X_O は Overlay 検証点での多項式の行列）。
  仕様の r_t = y_t − X β̂_t を、補正の学習点（A）と評価点（O）を分けた形にしたもの。
監視対象
1. 補正前の Alignment 面内傾向（a）：M3S、PCA T²・SPE、Mahalanobis（5次）
2. 推定した補正係数（ĉ）：Mahalanobis 距離、係数 SPC
3. 補正後の Overlay 残差（r）：M3S（よく使われる指標）、PCA T²・SPE、Mahalanobis（5次）
計測値ベクトルは [a, r] をつないだもので、監視手法はその一部（SliceMonitor）を見る。
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..anomaly_generator import AnomalySettings
from ..calibration import empirical_threshold
from ..config import make_rng
from ..evaluation import rate_with_ci
from ..feature_extraction import PolynomialFit, polynomial_design
from ..monitoring import (
    EWMADetector,
    M3SMonitor,
    MahalanobisMonitor,
    Monitor,
    PCAModel,
    PCASPEMonitor,
    PCAT2Monitor,
    PolynomialSPCMonitor,
    ShewhartDetector,
)
from ..monitoring.cusum import CUSUMDetector
from ..sampling import build_map
from ..simulation import MeasurementSystem, sample_stationary_coefficients
from ..temporal_process import coefficient_sequence
from .common import build_context, monitor_scores, save_table
from .phase2 import _conditions
from .temporal_engine import TemporalSetup, calibrate_thresholds, evaluate_conditions

TARGET_LABELS = {"alignment": "補正前Alignment", "coefficient": "補正係数", "overlay": "補正後Overlay残差"}
SCENARIOS = {
    "S1_linear": ("低次補正で除去できる異常", "X 方向だけの倍率（x に比例する X のずれ）"),
    "S2_cubic_radial": ("高次補正で除去できる異常", "3次の放射状歪み（B1 と同じ形）"),
    "S3_zernike89": ("補正モデル次数では表現できない異常", "n = 8〜9 の Zernike（B7 と同じ形）"),
    "S3_local": ("補正モデル次数では表現できない異常", "局所変形（B3 と同じ形）"),
    "S3_single_shot": ("補正モデル次数では表現できない異常", "単一 Shot のずれ（B9 と同じ形）"),
    "S4_alignment_flyer": ("ノイズ・外れ値を過学習する条件", "Alignment の1マークだけの計測外れ値（実際のずれはない）"),
}
SCENARIO_PATTERN = {"S2_cubic_radial": "B1", "S3_zernike89": "B7", "S3_local": "B3", "S3_single_shot": "B9"}


class SliceMonitor(Monitor):
    """つないだ計測値ベクトルの一部だけを見る監視手法。"""

    def __init__(self, inner: Monitor, part: slice, name: str):
        self.inner = inner
        self.part = part
        self.name = name
        self.family = inner.family

    def fit(self, train):
        self.inner.fit(train[:, self.part])
        return self

    def score(self, values):
        return self.inner.score(values[:, self.part])

    def vector(self, values):
        return self.inner.vector(values[:, self.part])


@dataclass
class APCSystem:
    """係数 → [Alignment 計測値, 補正後 Overlay 残差]。TemporalSetup の計測系として使える。"""

    alignment: MeasurementSystem
    overlay: MeasurementSystem
    correction: PolynomialFit
    overlay_design: np.ndarray  # O × P（補正多項式を Overlay 検証点で評価する行列）

    @property
    def process(self):
        return self.alignment.process

    @property
    def n_alignment(self) -> int:
        return 2 * self.alignment.n_points

    def correction_coefficients(self, alignment_values: np.ndarray) -> np.ndarray:
        return self.correction.coefficients(alignment_values)

    def correction_at_overlay(self, coefficients: np.ndarray) -> np.ndarray:
        p = self.correction.n_terms
        return np.concatenate([coefficients[:, :p] @ self.overlay_design.T, coefficients[:, p:] @ self.overlay_design.T], axis=1)

    def combine(self, alignment_values: np.ndarray, overlay_values: np.ndarray) -> np.ndarray:
        residual = overlay_values - self.correction_at_overlay(self.correction_coefficients(alignment_values))
        return np.concatenate([alignment_values, residual], axis=1)

    def measure(self, coefficients: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        return self.combine(self.alignment.measure(coefficients, rng), self.overlay.measure(coefficients, rng))

    def shift(self, alignment_shift: np.ndarray, overlay_shift: np.ndarray) -> np.ndarray:
        """潜在値の変化（A 上・O 上）が [a, r] に与える変化（補正が線形なので足し算で済む）。"""
        return self.combine(alignment_shift, overlay_shift)

    def true_residual_rms(self, coefficients, alignment_values, overlay_shift=None) -> np.ndarray:
        """計測誤差を含まない Overlay 残差（真のずれ − 補正量）の RMS（点ごとの XY の大きさ）。"""
        latent = self.overlay.latent(coefficients)
        if overlay_shift is not None:
            latent = latent + overlay_shift
        residual = latent - self.correction_at_overlay(self.correction_coefficients(alignment_values))
        n = residual.shape[1] // 2
        return np.sqrt(np.mean(residual[:, :n] ** 2 + residual[:, n:] ** 2, axis=1))


def build_apc_system(ctx, apc: dict, correction_order: int, alignment_density: float, alignment_noise: float, rho: float | None = None):
    alignment_map = build_map(ctx.full_points, apc["alignment_map"]["layout"], alignment_density, order=max(correction_order, 1))
    alignment_points = ctx.full_points.subset(alignment_map.point_index)
    overlay_all = ctx.layout.points("overlay")
    overlay_map = build_map(overlay_all, apc["overlay_map"]["layout"], float(apc["overlay_map"]["density"]), order=5)
    overlay_points = overlay_all.subset(overlay_map.point_index)
    alignment = ctx.system(alignment_points, noise_scale=alignment_noise, rho=rho)
    overlay = ctx.system(overlay_points, rho=rho)
    correction = PolynomialFit(alignment_points.x_norm, alignment_points.y_norm, correction_order)
    design = polynomial_design(overlay_points.x_norm, overlay_points.y_norm, correction_order)
    return APCSystem(alignment, overlay, correction, design)


def build_apc_monitors(system: APCSystem, apc: dict) -> dict[str, Monitor]:
    na = system.n_alignment
    part_a, part_o = slice(0, na), slice(na, None)
    order = int(apc["monitoring_order"])
    a_pts, o_pts = system.alignment.points, system.overlay.points
    monitors: dict[str, Monitor] = {}

    def add(target, inner, part, label):
        monitors[f"{target}:{label}"] = SliceMonitor(inner, part, f"{target}:{label}")

    add("alignment", M3SMonitor("XY"), part_a, "M3S")
    model_a = PCAModel(0.95, "raw")
    add("alignment", PCAT2Monitor(model_a), part_a, "T2")
    add("alignment", PCASPEMonitor(model_a), part_a, "SPE")
    try:
        add("alignment", MahalanobisMonitor(PolynomialFit(a_pts.x_norm, a_pts.y_norm, order)), part_a, f"MD_d{order}")
    except ValueError:
        pass
    add("coefficient", MahalanobisMonitor(system.correction), part_a, "MD")
    add("coefficient", PolynomialSPCMonitor(system.correction), part_a, "SPC")
    add("overlay", M3SMonitor("XY"), part_o, "M3S")
    model_o = PCAModel(0.95, "raw")
    add("overlay", PCAT2Monitor(model_o), part_o, "T2")
    add("overlay", PCASPEMonitor(model_o), part_o, "SPE")
    add("overlay", MahalanobisMonitor(PolynomialFit(o_pts.x_norm, o_pts.y_norm, order)), part_o, f"MD_d{order}")
    return monitors


def scenario_shift(ctx, system: APCSystem, scenario: str, params) -> tuple[np.ndarray, np.ndarray]:
    """1σ_dir の異常が A 上・O 上の潜在値に与える変位（n × 2N_A、n × 2N_O）。"""
    gen = ctx.anomalies
    a_pts, o_pts = system.alignment.points, system.overlay.points
    if scenario == "S1_linear":
        def raw(points):
            n = len(points)
            return np.concatenate([np.broadcast_to(points.x_norm, (len(params["n_idx"]), n)), np.zeros((len(params["n_idx"]), n))], axis=1)

        ref = raw(ctx.full_points)
        norm = np.linalg.norm(ref, axis=1)
        d = ref / norm[:, None]
        cov = ctx.reference.measured_covariance()
        sigma = np.sqrt(np.einsum("ij,jk,ik->i", d, cov, d))
        scale = (sigma / norm)[:, None]
        return scale * raw(a_pts), scale * raw(o_pts)
    if scenario == "S4_alignment_flyer":
        hit = np.zeros((len(params["n_idx"]), 2 * len(a_pts)))
        index = params["point"]
        hit[np.arange(len(index)), index + np.where(params["axis"] == 1, len(a_pts), 0)] = params["sigma"]
        return hit, np.zeros((len(index), 2 * len(o_pts)))
    pattern = SCENARIO_PATTERN[scenario]
    return gen.unit_fields(pattern, params, a_pts), gen.unit_fields(pattern, params, o_pts)


def scenario_params(ctx, system: APCSystem, scenario: str, n: int):
    rng = make_rng(ctx.seed, "apc", "params", scenario)
    if scenario == "S1_linear":
        return {"n_idx": np.arange(n)}
    if scenario == "S4_alignment_flyer":
        # 外れ値の大きさの基準は Mark 単位の計測誤差（基準ノイズの点ごとの標準偏差）
        sigma = float(np.sqrt(ctx.noise.mark_sigma_nm**2 + ctx.noise.shot_sigma_nm**2))
        return {"n_idx": np.arange(n), "point": rng.integers(0, len(system.alignment.points), n), "axis": rng.integers(0, 2, n), "sigma": sigma}
    return ctx.anomalies.draw(SCENARIO_PATTERN[scenario], rng, n)


def evaluate_condition(ctx, apc: dict, correction_order: int, alignment_density: float, alignment_noise: float, label: str):
    system = build_apc_system(ctx, apc, correction_order, alignment_density, alignment_noise)
    monitors = build_apc_monitors(system, apc)
    rng = make_rng(ctx.seed, "apc", label, "train")
    train_coef = coefficient_sequence(system.process, rng, 1, int(apc["n_train"]))[0]
    train = system.measure(train_coef, rng)
    for monitor in monitors.values():
        monitor.fit(train)

    def draw(purpose, n):
        rng_coef = make_rng(ctx.seed, "apc", purpose, "coef")
        rng_noise = make_rng(ctx.seed, "apc", purpose, "noise", label)
        coefficients = sample_stationary_coefficients(system.process, rng_coef, n)
        a = system.alignment.latent(coefficients) + system.alignment.noise.sample(rng_noise, n, system.alignment.points, ctx.layout.n_shots)
        o = system.overlay.latent(coefficients) + system.overlay.noise.sample(rng_noise, n, system.overlay.points, ctx.layout.n_shots)
        return coefficients, a, o

    alpha = float(apc["alpha"])
    _, cal_a, cal_o = draw("calibration", int(apc["n_calibration"]))
    cal = monitor_scores(monitors, system.combine(cal_a, cal_o))
    thresholds = np.array([empirical_threshold(cal[:, j], alpha) for j in range(cal.shape[1])])
    eval_coef, eval_a, eval_o = draw("evaluation", int(apc["n_evaluation"]))
    ev = monitor_scores(monitors, system.combine(eval_a, eval_o))
    normal_rms = system.true_residual_rms(eval_coef, eval_a)
    base = {"correction_order": correction_order, "alignment_density": alignment_density, "alignment_noise": alignment_noise, "condition": label, "n_alignment_points": system.alignment.n_points, "n_overlay_points": system.overlay.n_points}
    rows = []
    for j, name in enumerate(monitors):
        fpr = rate_with_ci(ev[:, j] > thresholds[j])
        rows.append({**base, "monitor": name, "target": name.split(":")[0], "scenario": "normal", "amplitude": 0.0, "detection_rate": fpr["rate"], "ci_low": fpr["ci_low"], "ci_high": fpr["ci_high"], "true_overlay_rms_nm": float(normal_rms.mean()), "n": fpr["n"]})
    n_rep = int(apc["n_replicates"])
    coef, base_a, base_o = draw("anomaly_base", n_rep)
    examples = {}
    for scenario in SCENARIOS:
        params = scenario_params(ctx, system, scenario, n_rep)
        shift_a, shift_o = scenario_shift(ctx, system, scenario, params)
        is_flyer = scenario == "S4_alignment_flyer"
        for amplitude in apc["amplitudes"]:
            a = base_a + float(amplitude) * shift_a
            o = base_o + float(amplitude) * shift_o
            combined = system.combine(a, o)
            scores = monitor_scores(monitors, combined)
            true_rms = system.true_residual_rms(coef, a, None if is_flyer else float(amplitude) * shift_o)
            for j, name in enumerate(monitors):
                result = rate_with_ci(scores[:, j] > thresholds[j])
                rows.append({**base, "monitor": name, "target": name.split(":")[0], "scenario": scenario, "amplitude": float(amplitude), "detection_rate": result["rate"], "ci_low": result["ci_low"], "ci_high": result["ci_high"], "true_overlay_rms_nm": float(true_rms.mean()), "n": result["n"]})
            if float(amplitude) == 8.0:
                coefficients = system.correction_coefficients(a[:1])
                examples[scenario] = {
                    "alignment": a[0], "overlay_before": o[0], "correction_at_overlay": system.correction_at_overlay(coefficients)[0],
                    "residual": combined[0, system.n_alignment:], "shift_overlay": float(amplitude) * shift_o[0],
                }
    return pd.DataFrame(rows), system, examples


def run(config: dict, workers: int | None = None, temporal: bool = True) -> dict[str, pd.DataFrame]:
    start = time.time()
    workers = int(config.get("workers", 1) if workers is None else workers)
    ctx = build_context(config)
    apc = config["apc"]
    frames, example_payload = [], {}
    standard_density = float(apc["alignment_map"]["density"])
    for order in apc["correction_orders"]:
        for density, noise, kind in ((standard_density, 1.0, "standard"), (float(apc["sparse_alignment_density"]), float(max(apc["alignment_noise_scales"])), "sparse_noisy")):
            label = f"order{order}_{kind}"
            try:
                frame, system, examples = evaluate_condition(ctx, apc, int(order), density, noise, label)
            except ValueError as error:
                print(f"[APC] {label} はスキップ（{error}）", flush=True)
                continue
            frame["alignment_condition"] = kind
            frames.append(frame)
            if kind == "standard":
                for scenario, values in examples.items():
                    for key, value in values.items():
                        example_payload[f"order{order}|{scenario}|{key}"] = value
                example_payload[f"order{order}|alignment_x"] = system.alignment.points.x_mm
                example_payload[f"order{order}|alignment_y"] = system.alignment.points.y_mm
                example_payload[f"order{order}|overlay_x"] = system.overlay.points.x_mm
                example_payload[f"order{order}|overlay_y"] = system.overlay.points.y_mm
            print(f"[APC] {label} {time.time() - start:.0f} 秒", flush=True)
    single = pd.concat(frames, ignore_index=True)
    single["scenario_label"] = single["scenario"].map(lambda s: SCENARIOS.get(s, ("正常", ""))[0])
    results = {"apc_single": single, "apc_scenarios": pd.DataFrame([{"scenario": k, "category": v[0], "description": v[1]} for k, v in SCENARIOS.items()])}
    if temporal:
        results["apc_temporal"], results["apc_temporal_arl0"] = _temporal(ctx, config, workers)
    for name, frame in results.items():
        save_table(frame, ctx.out / "metrics" / name)
    np.savez_compressed(ctx.out / "samples" / "apc_examples.npz", **example_payload)
    print(f"[APC] 完了 {time.time() - start:.0f} 秒", flush=True)
    return results


def _temporal(ctx, config, workers):
    """経時変化（Ramp）を Wafer ごとの補正（d_c = 3）の下で監視する：補正前・補正係数・補正後残差の EWMA。"""
    from .phase2 import run_temporal_study

    apc = config["apc"]
    settings = dict(apc["temporal"])
    rho = float(config["phase2"]["rho_values"][0])
    system = build_apc_system(ctx, apc, 3, float(apc["alignment_map"]["density"]), 1.0, rho=rho)
    monitors = build_apc_monitors(system, apc)
    rng = make_rng(ctx.seed, "apc", "temporal", "train")
    train = system.measure(coefficient_sequence(system.process, rng, 1, int(apc["n_train"]))[0], rng)
    for monitor in monitors.values():
        monitor.fit(train)
    lam = float(settings["lam"])
    detectors = []
    for name, monitor in monitors.items():
        if name.endswith(("M3S",)):
            detectors += [ShewhartDetector(monitor), EWMADetector(monitor, lam, "scalar")]
        else:
            detectors += [ShewhartDetector(monitor), EWMADetector(monitor, lam, "map")]
    for detector in detectors:
        detector.fit(train)
    setup = TemporalSetup(system, detectors, train.mean(axis=0))
    conditions = _conditions(settings["patterns"], settings["components"], settings["amplitudes"])

    # 成分の 1σ_dir の変位を [a, r] 上の変化に直す（補正の効果を含む）
    fields = {}
    for component in settings["components"]:
        params = ctx.anomalies.draw(component, make_rng(ctx.seed, "temporal_component", component), 1)
        fields[component] = system.shift(ctx.anomalies.unit_fields(component, params, system.alignment.points), ctx.anomalies.unit_fields(component, params, system.overlay.points))[0]
    delays, arl, _, _ = run_temporal_study(ctx, config, setup, conditions, settings, ("apc", "temporal"), workers, fields=fields)
    delays["target"] = delays["base"].str.split(":").str[0]
    return delays, arl
