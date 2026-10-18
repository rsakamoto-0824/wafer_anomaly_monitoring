"""監視手法（M1〜M6）を、実データの共通の計測点で組み立てる。

手法そのものは検証のコード（src/monitoring）をそのまま使う。実データに合わせて変えたのは次の2点だけ。
- M3S は計測できた値だけで計算する（補った値を使わない）。ObservedM3SMonitor。
- 多項式の次数が点の数に対して高すぎる（識別できない）とき、GPR の点が多すぎて計算できないときは、その手法を使わず理由を返す。
"""
from __future__ import annotations

import numpy as np

from ..feature_extraction import try_polynomial_fit
from ..monitoring import (
    GPRResidualMonitor,
    M3SMonitor,
    MahalanobisMonitor,
    Monitor,
    PCAModel,
    PCASPEMonitor,
    PCAT2Monitor,
    PolynomialSPCMonitor,
)
from ..wafer_geometry import PointSet
from .settings import PCA_COEF_ORDER, MethodOptions, selected_method_names

MAHALANOBIS_SHRINKAGE = "ledoit_wolf"  # 検証と同じ
MAX_GPR_POINTS = 1500  # GPR は点の数の3乗で計算が重くなる。これを超えると数十分以上かかるので使わない


def nan_m3s_by_axis(values: np.ndarray) -> np.ndarray:
    """欠測（NaN）を除いた M3S = |平均| + 3σ（X・Y、σ は不偏標準偏差）。"""
    n = values.shape[-1] // 2
    result = []
    for block in (values[..., :n], values[..., n:]):
        block = np.sort(block, axis=-1)  # 値を並べてから足す（点の順番によらず、丸め誤差まで同じ値にするため）
        result.append(np.abs(np.nanmean(block, axis=-1)) + 3.0 * np.nanstd(block, axis=-1, ddof=1))
    return np.stack(result, axis=-1)


class ObservedM3SMonitor(M3SMonitor):
    """計測できた値だけで M3S を計算する（補った値は使わない）。入力には欠測を NaN のまま渡す。"""

    uses_observed_only = True

    def fit(self, train: np.ndarray) -> "ObservedM3SMonitor":
        values = nan_m3s_by_axis(train)
        self.mean_ = values.mean(axis=0)
        self.sd_ = values.std(axis=0, ddof=1)
        return self

    def by_axis(self, values: np.ndarray) -> np.ndarray:
        return nan_m3s_by_axis(values)

    def standardized(self, values: np.ndarray) -> np.ndarray:
        return (nan_m3s_by_axis(values) - self.mean_) / self.sd_


def score_monitor(monitor: Monitor, filled: np.ndarray, observed: np.ndarray) -> np.ndarray:
    """M3S には欠測を NaN のままの値、それ以外には補った値を渡してスコアを計算する。"""
    return monitor.score(observed if getattr(monitor, "uses_observed_only", False) else filled)


def build_monitors(points: PointSet, options: MethodOptions) -> tuple[dict[str, Monitor], list[tuple[str, str]]]:
    """選んだ手法を作る。作れない手法は（名前, 理由）で返す。"""
    wanted = selected_method_names(options)
    monitors: dict[str, Monitor] = {}
    skipped: list[tuple[str, str]] = []
    polys = {}
    orders = sorted(set(options.spc_orders) | set(options.md_orders) | ({PCA_COEF_ORDER} if "coef" in options.pca_sources else set()))
    for order in orders:
        poly = try_polynomial_fit(points.x_norm, points.y_norm, order)
        if poly is not None:
            polys[order] = poly
    pca_models: dict[str, PCAModel] = {}
    for name in wanted:
        parts = name.split("_")
        if name == "M3S_XY":
            monitors[name] = ObservedM3SMonitor("XY")
        elif parts[0] in ("SPC", "MD"):
            order = int(parts[1][1:])
            if order not in polys:
                skipped.append((name, _poly_reason(order, len(points))))
                continue
            monitors[name] = PolynomialSPCMonitor(polys[order]) if parts[0] == "SPC" else MahalanobisMonitor(polys[order], MAHALANOBIS_SHRINKAGE)
        elif parts[0] in ("T2", "SPE"):
            tag = f"{parts[1]}_{parts[2]}"
            source = "raw" if parts[1] == "raw" else "coef"
            if source == "coef" and PCA_COEF_ORDER not in polys:
                skipped.append((name, _poly_reason(PCA_COEF_ORDER, len(points))))
                continue
            if tag not in pca_models:
                pca_models[tag] = PCAModel(int(parts[2][1:]) / 100.0, source, polys.get(PCA_COEF_ORDER) if source == "coef" else None)
            monitors[name] = PCAT2Monitor(pca_models[tag]) if parts[0] == "T2" else PCASPEMonitor(pca_models[tag])
        elif parts[0] == "GPR":
            if len(points) > MAX_GPR_POINTS:
                skipped.append((name, f"計測点が {len(points)} 点あり、GPR の計算が重すぎます（{MAX_GPR_POINTS} 点まで）"))
                continue
            monitors[name] = GPRResidualMonitor(points, parts[1], parts[2])
    return monitors, skipped


class OrRule:
    """複数の手法の OR 判定：どれか1つでも自分の管理限界を超えたら警報。

    各手法の管理限界を「校正期間で上から r 番目の値」という共通の水準にそろえ、統合した警報率
    （どれか1つでも超えた校正の計測の割合）が α 以下になる最大の r を選ぶ。
    検証の OrCombination（経験分布関数の最大値を校正）と同じ考え方。ただし校正の件数が少ないと、
    経験分布関数が最大値 1 で頭打ちになって警報を出せなくなるので、手法ごとの限界からの距離で表す。
    統合スコア = max_j (s_j − h_j) / (h_j − 校正の中央値_j)。0 を超えたら警報。
    """

    def __init__(self, names: list[str]):
        self.names = list(names)

    def fit(self, calibration_matrix: np.ndarray, alpha: float) -> "OrRule":
        ordered = -np.sort(-calibration_matrix, axis=0)
        chosen, chosen_rate = 0, 0.0
        for rank in range(len(ordered)):
            rate = float(np.mean((calibration_matrix > ordered[rank]).any(axis=1)))
            if rate > alpha:
                break
            chosen, chosen_rate = rank, rate
        self.limits_ = ordered[chosen]
        spread = self.limits_ - np.median(calibration_matrix, axis=0)
        fallback = calibration_matrix.std(axis=0, ddof=1)
        self.spread_ = np.where(spread > 0, spread, np.where(fallback > 0, fallback, 1.0))
        self.calibration_rate_ = chosen_rate
        return self

    def transform(self, score_matrix: np.ndarray) -> np.ndarray:
        return np.max((score_matrix - self.limits_) / self.spread_, axis=1)


def _poly_reason(order: int, n_points: int) -> str:
    n_terms = (order + 1) * (order + 2) // 2
    return f"{order}次の多項式（{n_terms} 項）は、共通の計測点 {n_points} 点では係数を決められません"


def monitor_details(name: str, monitor: Monitor) -> str:
    """学習した手法の中身（主成分の数、縮小推定の強さ、GPR の超パラメータなど）。"""
    if isinstance(monitor, (PCAT2Monitor, PCASPEMonitor)):
        model = monitor.model
        return f"主成分 {model.k_} 個（寄与率 {100 * model.explained_:.1f}%）"
    if isinstance(monitor, MahalanobisMonitor):
        return f"係数 {len(monitor.mean_)} 個、縮小推定の強さ {monitor.shrinkage_:.3f}"
    if isinstance(monitor, PolynomialSPCMonitor):
        return f"係数 {len(monitor.mean_)} 個"
    if isinstance(monitor, GPRResidualMonitor):
        texts = []
        for axis, params in zip("XY", monitor.params_):
            texts.append(
                f"{axis}: 個体差 {params['signal_sd']:.2f} nm・長さ {params['length_mm']:.0f} mm・"
                f"Shot 誤差 {params['shot_sd']:.2f} nm・Mark 誤差 {params['mark_sd']:.2f} nm"
            )
        return " / ".join(texts)
    if isinstance(monitor, M3SMonitor):
        return f"正常時の M3S 平均 X {monitor.mean_[0]:.2f}・Y {monitor.mean_[1]:.2f} nm"
    return ""
