"""各 Phase で共通に使う部品：設定から Wafer・工程・計測系・監視手法を組み立てる。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ..anomaly_generator import AnomalyGenerator, AnomalySettings
from ..config import make_rng, output_dir, resolve_path
from ..feature_extraction import try_polynomial_fit
from ..monitoring import (
    CUSUMDetector,
    EWMADetector,
    GPRResidualMonitor,
    M3SMonitor,
    MahalanobisMonitor,
    Monitor,
    PCAModel,
    PCASPEMonitor,
    PCAT2Monitor,
    PolynomialSPCMonitor,
    ShewhartDetector,
    SmoothedMaps,
    StepInput,
    TemporalDetector,
)
from ..simulation import MeasurementSystem, NoiseModel, ProcessModel, build_process_model
from ..temporal_process import CoefficientStream, coefficient_sequence
from ..wafer_geometry import PointSet, WaferLayout, build_layout

FAMILY_LABELS = {
    "M1": "M3S",
    "M2": "多項式係数SPC",
    "M3": "Mahalanobis距離",
    "M4": "PCA T²",
    "M5": "PCA SPE",
    "M6": "GPR残差",
    "M7": "EWMA",
    "M8": "CUSUM",
    "OR": "OR統合",
    "Oracle": "方向既知の射影管理図（参考）",
}


@dataclass
class Context:
    config: dict
    seed: int
    layout: WaferLayout
    process: ProcessModel
    noise: NoiseModel
    full_points: PointSet
    reference: MeasurementSystem
    anomalies: AnomalyGenerator
    out: Path
    cache: Path

    def system(self, points: PointSet | None = None, noise_scale: float = 1.0, rho: float | None = None) -> MeasurementSystem:
        process = self.process if rho is None else self.process.with_rho(rho)
        noise = self.noise.scaled(self.noise.scale * noise_scale)
        return MeasurementSystem(process, noise, self.full_points if points is None else points, self.layout.n_shots)


def build_context(config: dict) -> Context:
    layout = build_layout(config["wafer"], config["marks"])
    process = build_process_model(config["normal_process"])
    noise = NoiseModel.from_config(config["noise"])
    full_points = layout.points("alignment")
    reference = MeasurementSystem(process, noise, full_points, layout.n_shots)
    anomalies = AnomalyGenerator(process, layout, reference, AnomalySettings.from_config(config.get("anomaly", {})))
    out = output_dir(config)
    cache = resolve_path(config, "cache_dir", "results/cache")
    for folder in (out / "metrics", out / "figures", out / "samples", cache):
        folder.mkdir(parents=True, exist_ok=True)
    return Context(config, int(config["seed"]), layout, process, noise, full_points, reference, anomalies, out, cache)


def training_data(ctx: Context, system: MeasurementSystem, n_train: int, *key) -> np.ndarray:
    """時系列順の正常データ（1本の AR(1) 系列の n_train 枚）。"""
    rng = make_rng(ctx.seed, *key, "train")
    coefficients = coefficient_sequence(system.process, rng, 1, n_train)[0]
    return system.measure(coefficients, rng)


# ---------------------------------------------------------------------- 監視手法
def build_single_monitors(points: PointSet, monitoring: dict, orders=None, include=None) -> tuple[dict[str, Monitor], list[dict]]:
    """1 Wafer の監視手法（M1〜M6）を作る。識別できない多項式次数はスキップして記録する。"""
    monitors: dict[str, Monitor] = {}
    skipped = []
    for axis in ("XY", "X", "Y"):
        monitors[f"M3S_{axis}"] = M3SMonitor(axis)
    orders = monitoring["polynomial_orders"] if orders is None else orders
    polys = {}
    for order in sorted(set(orders) | {monitoring["pca_coef_order"]}):
        poly = try_polynomial_fit(points.x_norm, points.y_norm, order)
        if poly is None:
            skipped.append({"order": order, "n_points": len(points), "reason": "識別不能（点数・ランク不足）"})
            continue
        polys[order] = poly
    for order in orders:
        if order in polys:
            monitors[f"SPC_d{order}"] = PolynomialSPCMonitor(polys[order])
            monitors[f"MD_d{order}"] = MahalanobisMonitor(polys[order], monitoring.get("mahalanobis_shrinkage", "ledoit_wolf"))
    for source in monitoring["pca_sources"]:
        poly = polys.get(monitoring["pca_coef_order"]) if source == "coef" else None
        if source == "coef" and poly is None:
            continue
        for ratio in monitoring["pca_variance_ratios"]:
            model = PCAModel(ratio, source, poly)
            for monitor in (PCAT2Monitor(model), PCASPEMonitor(model)):
                monitors[monitor.name] = monitor
    for kernel in monitoring["gpr_kernels"]:
        for statistic in monitoring["gpr_statistics"]:
            monitor = GPRResidualMonitor(points, kernel, statistic)
            monitors[monitor.name] = monitor
    if include is not None:
        monitors = {name: monitor for name, monitor in monitors.items() if name in include}
    return monitors, skipped


def fit_monitors(monitors: dict[str, Monitor], train: np.ndarray) -> dict[str, Monitor]:
    for monitor in monitors.values():
        monitor.fit(train)
    return monitors


CUSUM_MODE_BY_FAMILY = {"M1": "scalar", "M2": "componentwise", "M3": "vector", "M4": "vector", "M5": "scalar", "M6": "scalar"}


def build_temporal_detectors(
    monitors: dict[str, Monitor], bases, lambdas, ks, shewhart: bool = True, md_scalar: bool = False
) -> list[TemporalDetector]:
    """土台の手法ごとに Shewhart・EWMA（λ）・CUSUM（k）の検出器を作る。"""
    detectors: list[TemporalDetector] = []
    for base in bases:
        monitor = monitors[base]
        if shewhart:
            detectors.append(ShewhartDetector(monitor))
        for lam in lambdas:
            mode = "scalar" if monitor.family == "M1" else "map"
            detectors.append(EWMADetector(monitor, lam, mode))
            if md_scalar and monitor.family == "M3":
                detectors.append(EWMADetector(monitor, lam, "scalar"))
        for k in ks:
            detectors.append(CUSUMDetector(monitor, k, CUSUM_MODE_BY_FAMILY[monitor.family]))
    return detectors


def detector_table(monitors: dict[str, Monitor], detectors: list[TemporalDetector]) -> pd.DataFrame:
    rows = []
    for name, monitor in monitors.items():
        rows.append({"detector": name, "family": monitor.family, "base": name, "scheme": "shewhart", "param": np.nan})
    for detector in detectors:
        if detector.scheme == "shewhart":
            continue
        param = detector.smoothing if detector.scheme == "ewma" else detector.k
        scheme = detector.scheme + ("-scalar" if getattr(detector, "mode", "") == "scalar" and detector.scheme == "ewma" else "")
        rows.append({"detector": detector.name, "family": detector.family, "base": detector.monitor.name, "scheme": scheme, "param": param})
    return pd.DataFrame(rows)


class SequenceRunner:
    """正常系列を時系列順に流し、状態をもつ検出器（EWMA・CUSUM）の状態を進める。"""

    def __init__(self, system: MeasurementSystem, detectors: list[TemporalDetector], center: np.ndarray):
        self.system = system
        self.detectors = detectors
        self.stateful = [d for d in detectors if d.scheme != "shewhart" and not (d.scheme == "ewma" and d.lam is not None)]
        self.lambdas = sorted({d.lam for d in detectors if d.lam is not None})
        self.center = center

    def run_history(self, rng: np.random.Generator, n_series: int, history: int):
        """history 枚の正常 Wafer を流したあとの状態と、次の（評価する）Wafer の係数・計測値を返す。"""
        stream = CoefficientStream(self.system.process, rng, n_series)
        maps = SmoothedMaps(self.lambdas, self.center, n_series)
        states = {d.name: d.init_state(n_series) for d in self.stateful}
        for _ in range(history):
            values = self.system.measure(stream.next(), rng)
            maps, step = maps.step(values)
            for detector in self.stateful:
                states[detector.name], _ = detector.update(states[detector.name], step)
        coefficients = stream.next()
        latent = self.system.latent(coefficients)
        values = latent + self.system.noise.sample(rng, n_series, self.system.points, self.system.n_shots_layout)
        return maps, states, latent, values

    def final_statistics(self, maps: SmoothedMaps, states: dict, values: np.ndarray) -> np.ndarray:
        """評価する Wafer での全検出器の統計量（n × 検出器数）。状態は書き換えない。"""
        _, step = maps.step(values)
        columns = []
        for detector in self.detectors:
            state = states.get(detector.name)
            columns.append(detector.update(state, step)[1])
        return np.column_stack(columns)


def monitor_scores(monitors: dict[str, Monitor], values: np.ndarray) -> np.ndarray:
    return np.column_stack([monitor.score(values) for monitor in monitors.values()])


def save_table(frame: pd.DataFrame, path_without_suffix: Path) -> None:
    """CSV と Parquet の両方で保存する。"""
    path_without_suffix.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path_without_suffix.with_suffix(".csv"), index=False, encoding="utf-8")
    frame.to_parquet(path_without_suffix.with_suffix(".parquet"), index=False)
