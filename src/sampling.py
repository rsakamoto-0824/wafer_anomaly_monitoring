"""計測マップ（どの点を測るか）を作る。

- 全点：有効な全マーク（外周の部分 Shot も含む）。
- 間引き（50%・25% など）：4マークがそろう Shot から Shot 単位で選ぶ（配置どうしで点数を同じにするため）。
  - realistic：実計測マップに準じた配置。同心円の3区画（内側 < 0.4R、中間 < 0.75R、外周）に
    15 : 35 : 50 の割合で配り、区画の中では方位角の順に等間隔で選ぶ（外周を厚く測る一般的なマップを模した仮定）。
  - uniform：均等配置。Shot 中心の最遠点サンプリング（中心に近い Shot から始める）。
  - d_optimal：監視多項式（既定は5次）の情報行列の行列式 det(XᵀX) を最大にする（交換法）。
  - i_optimal：平均予測分散 tr((XᵀX)⁻¹ M) を最小にする（交換法）。評価領域（予測対象）は
    全点マップの全マーク位置で、M = X_refᵀ X_ref / N_ref。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .feature_extraction import polynomial_design
from .wafer_geometry import PointSet

LAYOUT_KINDS = ("realistic", "uniform", "d_optimal", "i_optimal")
RING_EDGES = (0.4, 0.75)
RING_WEIGHTS = (0.15, 0.35, 0.50)


@dataclass(frozen=True)
class SamplingMap:
    name: str
    kind: str
    fraction: float
    point_index: np.ndarray  # 全点マップの中の番号

    @property
    def n_points(self) -> int:
        return len(self.point_index)


def full_map(points: PointSet) -> SamplingMap:
    return SamplingMap("full", "full", 1.0, np.arange(len(points)))


def build_map(points: PointSet, kind: str, fraction: float, order: int = 5) -> SamplingMap:
    """全点マップ points から、割合 fraction の点数になるよう Shot 単位で選ぶ。"""
    if kind == "full" or fraction >= 1.0:
        return full_map(points)
    if kind not in LAYOUT_KINDS:
        raise ValueError(f"配置は {LAYOUT_KINDS} のいずれか: {kind}")
    shots, marks_per_shot = complete_shots(points)
    n_select = int(round(fraction * len(points) / marks_per_shot))
    if not 1 <= n_select <= len(shots):
        raise ValueError(f"選べる Shot 数を超えている（{n_select} / {len(shots)}）")
    centers = np.array([[points.x_mm[points.shot_index == s].mean(), points.y_mm[points.shot_index == s].mean()] for s in shots])
    if kind == "realistic":
        chosen = _ring_selection(centers, n_select, points.radius_mm)
    elif kind == "uniform":
        chosen = _farthest_point(centers, n_select)
    else:
        start = _farthest_point(centers, n_select)
        chosen = _exchange(points, shots, start, order, criterion="D" if kind == "d_optimal" else "I")
    selected_shots = shots[np.sort(chosen)]
    index = np.flatnonzero(np.isin(points.shot_index, selected_shots))
    return SamplingMap(f"{kind}_{int(round(fraction * 100))}", kind, fraction, index)


def complete_shots(points: PointSet) -> tuple[np.ndarray, int]:
    """全マークがそろう Shot の番号と、Shot あたりのマーク数。"""
    shots, counts = np.unique(points.shot_index, return_counts=True)
    marks_per_shot = int(counts.max())
    return shots[counts == marks_per_shot], marks_per_shot


def _ring_selection(centers: np.ndarray, n_select: int, radius: float) -> np.ndarray:
    r_norm = np.hypot(centers[:, 0], centers[:, 1]) / radius
    ring = np.digitize(r_norm, RING_EDGES)
    available = np.array([(ring == k).sum() for k in range(3)])
    quota = _allocate(n_select, np.asarray(RING_WEIGHTS), available)
    chosen = []
    for k in range(3):
        members = np.flatnonzero(ring == k)
        if quota[k] == 0:
            continue
        angle = np.arctan2(centers[members, 1], centers[members, 0])
        members = members[np.argsort(angle)]
        picks = np.floor((np.arange(quota[k]) + 0.5) * len(members) / quota[k]).astype(int)
        chosen.extend(members[picks])
    return np.array(chosen)


def _allocate(total: int, weights: np.ndarray, available: np.ndarray) -> np.ndarray:
    """重みに比例して配り、区画の Shot 数を超えた分は残りの区画へ回す。"""
    quota = np.zeros(len(weights), dtype=int)
    remaining = total
    open_ = available > 0
    while remaining > 0 and open_.any():
        share = weights * open_
        raw = remaining * share / share.sum()
        add = np.floor(raw).astype(int)
        leftover = remaining - add.sum()
        order = np.argsort(-(raw - add))
        for k in order[:leftover]:
            add[k] += 1
        add = np.minimum(add, available - quota)
        quota += add
        remaining = total - quota.sum()
        open_ = quota < available
        if add.sum() == 0:
            break
    return quota


def _farthest_point(centers: np.ndarray, n_select: int) -> np.ndarray:
    first = int(np.argmin(np.hypot(centers[:, 0], centers[:, 1])))
    chosen = [first]
    dist = np.hypot(centers[:, 0] - centers[first, 0], centers[:, 1] - centers[first, 1])
    while len(chosen) < n_select:
        nxt = int(np.argmax(dist))
        chosen.append(nxt)
        dist = np.minimum(dist, np.hypot(centers[:, 0] - centers[nxt, 0], centers[:, 1] - centers[nxt, 1]))
    return np.array(chosen)


def _exchange(points: PointSet, shots: np.ndarray, start: np.ndarray, order: int, criterion: str, max_passes: int = 30) -> np.ndarray:
    """Shot の入れ替え（交換法）で D 基準または I 基準を改善する。"""
    design_all = polynomial_design(points.x_norm, points.y_norm, order)
    blocks = [design_all[points.shot_index == s] for s in shots]
    gram_blocks = np.array([b.T @ b for b in blocks])
    moment = design_all.T @ design_all / len(design_all)  # 評価領域＝全点マップの全マーク

    def loss(selection: np.ndarray) -> float:
        gram = gram_blocks[selection].sum(axis=0)
        sign, logdet = np.linalg.slogdet(gram)
        if sign <= 0 or not np.isfinite(logdet):
            return np.inf
        if criterion == "D":
            return -logdet
        return float(np.trace(np.linalg.solve(gram, moment)))

    current = np.array(start)
    best = loss(current)
    for _ in range(max_passes):
        improved = False
        for position in range(len(current)):
            outside = np.setdiff1d(np.arange(len(shots)), current)
            trial = current.copy()
            losses = np.empty(len(outside))
            for i, candidate in enumerate(outside):
                trial[position] = candidate
                losses[i] = loss(trial)
            k = int(np.argmin(losses))
            if losses[k] < best - 1e-10 * max(1.0, abs(best)):
                best = losses[k]
                current[position] = outside[k]
                improved = True
        if not improved:
            break
    return current
