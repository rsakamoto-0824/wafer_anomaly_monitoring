"""異常の注入試験：実データの正常 Wafer に、検証と同じ形の異常を足して、同じ誤報率で検出率・検出遅延を比べる。

実データには「どの Wafer が異常か」の正解がふつうはないので、検証の Phase 1（1 Wafer）・Phase 2（経時変化）を
「正常のばらつきは実データ、異常は検証と同じ形」で行う（半分だけ模擬にした試験）。
- 土台にする正常 Wafer：校正期間の計測（学習に使っていないので、スコアが小さめに出ない）。
- 異常の大きさ：検証の仕様 7.3 と同じ σ_dir（異常の形の向きに、正常 Wafer を射影したときの標準偏差）の倍数。
  σ_dir は学習期間の実データから求める。nm での大きさ（計測点での RMS）も結果に出す。
- 異常の形：検証の AnomalyGenerator と同じ式（B1〜B5・B7〜B9、経時変化の成分）。B6 は模擬データの係数の相関を使う形なので除く。
  B10 は「全点の位置の無作為な入れ替え」（平均・σ が厳密に同じ）。
- 経時変化：校正期間の Wafer をブロック単位で並べた系列の変化点以降に、Step・Ramp などの形で足す。
  変化点より前に警報が出た系列は遅延の集計から除く（条件付き期待遅延。検証と同じ）。
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from ..anomaly_generator import AnomalyGenerator, AnomalySettings, anomaly_size_summary
from ..anomaly_generator import SHAPE_DESCRIPTIONS, SINGLE_WAFER_PATTERNS, TEMPORAL_COMPONENTS
from ..config import make_rng
from ..evaluation import conditional_delays, delay_summary, first_alarm_delays, wilson_interval
from ..temporal_process import TEMPORAL_PATTERNS, temporal_profile
from ..wafer_geometry import PointSet
from .errors import check_cancel
from .methods import score_monitor
from .settings import TEMPORAL_PROFILE_PARAMS
from .temporal import block_bootstrap_indices, detector_label, run_detectors

PATTERN_LABELS = {**SINGLE_WAFER_PATTERNS, "B10": "平均・分散が変わらない面内形状異常（点の入れ替え）"}
PATTERN_DESCRIPTIONS = {**SHAPE_DESCRIPTIONS, "B10": "全点の位置を無作為に入れ替える（X・Y の値の組を一緒に動かす。平均・標準偏差は厳密に同じ）"}
COMPONENT_LABELS = TEMPORAL_COMPONENTS
PROFILE_LABELS = TEMPORAL_PATTERNS
NO_ANOMALY = "正常（注入なし）"


class EmpiricalShapes(AnomalyGenerator):
    """実データの計測点で、検証と同じ異常の形を作る。

    AnomalyGenerator は模擬データの工程モデルから σ_dir を求めるが、ここでは実データから求めるので使わない。
    形を作る raw_field と、無作為なパラメータを引く draw が参照する属性（設定・Wafer 半径・計測点・Zernike の正規化）
    だけを用意し、親の __init__（模擬データの共分散を作る）は呼ばない。
    """

    def __init__(self, points: PointSet, settings: AnomalySettings | None = None, normalization: str = "rms"):
        self.settings = settings or AnomalySettings()
        self.process = SimpleNamespace(normalization=normalization)
        self.layout = SimpleNamespace(radius_mm=points.radius_mm)
        self.reference = SimpleNamespace(points=points)
        self.points = points

    def empirical_unit_fields(self, pattern: str, params: dict, train_centered: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """1σ_dir の異常（n × 2N、nm）と σ_dir（n、nm）。σ_dir は学習期間の実データの射影の標準偏差。"""
        shape = self.raw_field(pattern, params, self.points)
        norm = np.linalg.norm(shape, axis=1)
        if np.any(norm <= 0):
            raise ValueError(f"{pattern}：計測点に掛からない形になった")
        direction = shape / norm[:, None]
        sigma_dir = (train_centered @ direction.T).std(axis=0, ddof=1)
        return sigma_dir[:, None] * direction, sigma_dir


def available_patterns(patterns, has_direction: bool) -> tuple[list[str], list[tuple[str, str]]]:
    usable, skipped = [], []
    for pattern in patterns:
        if pattern == "B8" and not has_direction:
            skipped.append((pattern, "Direction（Scan 方向）の列がないため"))
        else:
            usable.append(pattern)
    return usable, skipped


def single_wafer_test(
    dataset,
    monitors: dict,
    thresholds: dict[str, float],
    or_model: tuple | None,
    options,
    seed: int,
    progress=None,
    cancel=None,
) -> tuple[pd.DataFrame, list]:
    """1 Wafer の注入試験。戻り値は（パターン × 大きさ × 手法の検出率の表, 使えなかったパターン）。"""
    calibration = dataset.rows("校正")
    train = dataset.rows("学習")
    base_filled = dataset.filled[calibration]
    base_observed = dataset.observed[calibration]
    train_centered = dataset.filled[train] - dataset.filled[train].mean(axis=0)
    shapes = EmpiricalShapes(dataset.points)
    patterns, skipped = available_patterns(options.single_patterns, dataset.prepared.check.has_direction)
    replicates = int(options.single_replicates)
    pick = make_rng(seed, "injection", "single", "base").integers(0, len(calibration), replicates)
    names = list(monitors)
    rows = []

    def evaluate(pattern, amplitude, filled, observed, size_rms, sigma_dir):
        scores = np.column_stack([score_monitor(monitors[name], filled, observed) for name in names])
        flags = {name: scores[:, j] > thresholds[name] for j, name in enumerate(names)}
        if or_model is not None:
            or_label, combination, threshold = or_model
            members = [names.index(member) for member in combination.names]
            flags[or_label] = combination.transform(scores[:, members]) > threshold
        for method, flag in flags.items():
            hits = int(flag.sum())
            low, high = wilson_interval(hits, len(flag))
            rows.append(
                {
                    "pattern": pattern,
                    "pattern_label": PATTERN_LABELS.get(pattern, pattern),
                    "amplitude_sigma": amplitude,
                    "rms_nm": size_rms,
                    "sigma_dir_nm": sigma_dir,
                    "method": method,
                    "n": len(flag),
                    "detected": hits,
                    "detection_rate": hits / len(flag),
                    "ci_low": float(low),
                    "ci_high": float(high),
                }
            )

    evaluate(NO_ANOMALY, 0.0, base_filled[pick], base_observed[pick], 0.0, np.nan)
    total = max(1, len(patterns) * len(options.single_amplitudes))
    done = 0
    for pattern in patterns:
        check_cancel(cancel)
        rng = make_rng(seed, "injection", "single", pattern)
        if pattern == "B10":
            permutation = np.argsort(rng.random((replicates, dataset.n_points)), axis=1)
            evaluate(pattern, np.nan, _permute(base_filled[pick], permutation), _permute(base_observed[pick], permutation), np.nan, np.nan)
            done += len(options.single_amplitudes)
            continue
        params = shapes.draw(pattern, rng, replicates)
        unit, sigma_dir = shapes.empirical_unit_fields(pattern, params, train_centered)
        for amplitude in sorted(options.single_amplitudes):
            delta = amplitude * unit
            size = anomaly_size_summary(delta)["rms_nm"]
            evaluate(pattern, float(amplitude), base_filled[pick] + delta, base_observed[pick] + delta, size, float(np.mean(sigma_dir)))
            done += 1
            if progress is not None:
                progress(done / total, f"1 Wafer の注入試験（{pattern}・{amplitude:g}σ）")
    return pd.DataFrame(rows), skipped


def _permute(values: np.ndarray, permutation: np.ndarray) -> np.ndarray:
    n = values.shape[1] // 2
    rows = np.arange(len(values))[:, None]
    return np.concatenate([values[:, :n][rows, permutation], values[:, n:][rows, permutation]], axis=1)


def single_wafer_summary(table: pd.DataFrame) -> pd.DataFrame:
    """手法ごとの平均検出率（注入したすべてのパターン・大きさ）と、M3S の検出率が 10% 未満の条件での平均。"""
    anomalous = table[table["pattern"] != NO_ANOMALY]
    if anomalous.empty:
        return pd.DataFrame()
    summary = anomalous.groupby("method")["detection_rate"].mean().rename("mean_detection").to_frame()
    false_alarm = table[table["pattern"] == NO_ANOMALY].set_index("method")["detection_rate"].rename("false_alarm_rate")
    summary = summary.join(false_alarm)
    m3s = anomalous[anomalous["method"] == "M3S_XY"]
    if not m3s.empty:
        blind = m3s.loc[m3s["detection_rate"] < 0.10, ["pattern", "amplitude_sigma"]]
        key = anomalous.merge(blind, on=["pattern", "amplitude_sigma"])
        if not key.empty:
            summary = summary.join(key.groupby("method")["detection_rate"].mean().rename("mean_detection_m3s_blind"))
            summary["n_m3s_blind_conditions"] = len(blind)
    return summary.sort_values("mean_detection", ascending=False).reset_index()


def temporal_test(dataset, detectors, thresholds: np.ndarray, center: np.ndarray, options, temporal_options, seed: int, progress=None, cancel=None) -> pd.DataFrame:
    """経時変化の注入試験。系列 = 校正期間の Wafer をブロック単位で並べたもの（全条件で同じ系列＝CRN）。"""
    calibration = dataset.rows("校正")
    train = dataset.rows("学習")
    base_filled = dataset.filled[calibration]
    base_observed = dataset.observed[calibration]
    train_centered = dataset.filled[train] - dataset.filled[train].mean(axis=0)
    shapes = EmpiricalShapes(dataset.points)
    pre, window = int(options.temporal_pre_length), int(options.temporal_window)
    length, onset = pre + window, pre + 1
    n_series = int(options.temporal_series)
    rng = make_rng(seed, "injection", "temporal", "base")
    index = block_bootstrap_indices(len(calibration), n_series, length, temporal_options.block_length, rng)

    conditions = [("none", "none", 0.0)]
    for component in options.temporal_components:
        for profile in options.temporal_profiles:
            for amplitude in sorted(options.temporal_amplitudes):
                conditions.append((component, profile, float(amplitude)))
    units = {}
    for component in options.temporal_components:
        unit, sigma_dir = shapes.empirical_unit_fields(component, {"n": 1}, train_centered)
        units[component] = (unit[0], float(sigma_dir[0]))

    rows = []
    for number, (component, profile, amplitude) in enumerate(conditions):
        check_cancel(cancel)
        if component == "none":
            drift = np.zeros((length, dataset.filled.shape[1]))
            sigma_dir = np.nan
        else:
            unit, sigma_dir = units[component]
            drift = amplitude * temporal_profile(profile, length, onset, TEMPORAL_PROFILE_PARAMS)[:, None] * unit[None, :]
        statistics = np.empty((n_series, length, len(detectors)))

        def provider(t, drift=drift):
            return base_filled[index[:, t]] + drift[t], base_observed[index[:, t]] + drift[t]

        def on_step(t, values, statistics=statistics):
            statistics[:, t, :] = values

        run_detectors(detectors, center, n_series, length, provider, on_step, cancel)
        for j, detector in enumerate(detectors):
            delays, before = first_alarm_delays(statistics[:, :, j], thresholds[j], onset)
            clean, pre_change_rate = conditional_delays(delays, before)
            summary = delay_summary(clean, window) if len(clean) else {"detection_rate": np.nan, "rmst_delay": np.nan, "median_delay": np.nan}
            rows.append(
                {
                    "component": component,
                    "component_label": "変化なし（参考）" if component == "none" else COMPONENT_LABELS.get(component, component),
                    "profile": profile,
                    "profile_label": "" if component == "none" else PROFILE_LABELS.get(profile, profile),
                    "amplitude_sigma": amplitude,
                    "sigma_dir_nm": sigma_dir,
                    "detector": detector.name,
                    "detector_label": detector_label(detector),
                    "n_series": n_series,
                    "n_clean": len(clean),
                    "pre_change_false_alarm_rate": pre_change_rate,
                    "detection_rate": summary["detection_rate"],
                    "detection_ci_low": summary.get("detection_ci_low", np.nan),
                    "detection_ci_high": summary.get("detection_ci_high", np.nan),
                    "rmst_delay": summary["rmst_delay"],
                    "median_delay": summary["median_delay"],
                    "window": window,
                }
            )
        if progress is not None:
            progress((number + 1) / len(conditions), f"経時変化の注入試験（{number + 1} / {len(conditions)} 条件）")
    return pd.DataFrame(rows)


def temporal_summary(table: pd.DataFrame) -> pd.DataFrame:
    """検出器ごとの平均（変化のある全条件）。RMST が小さいほど早く気づく。"""
    changed = table[table["component"] != "none"]
    if changed.empty:
        return pd.DataFrame()
    summary = changed.groupby(["detector", "detector_label"]).agg(
        mean_rmst_delay=("rmst_delay", "mean"),
        mean_detection_rate=("detection_rate", "mean"),
        pre_change_false_alarm_rate=("pre_change_false_alarm_rate", "mean"),
    )
    null = table[table["component"] == "none"].set_index("detector")["rmst_delay"].rename("null_rmst_delay")
    summary = summary.reset_index().merge(null, left_on="detector", right_index=True, how="left")
    return summary.sort_values("mean_rmst_delay").reset_index(drop=True)
