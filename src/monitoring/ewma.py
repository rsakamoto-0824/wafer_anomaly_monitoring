"""M7：EWMA。S_t = λ x_t + (1 − λ) S_{t−1}（S_0 は正常時の平均）。

2 通りの入力を扱う。
- map（計測値の EWMA）：計測値そのもの z_t を EWMA で平滑化し、平滑化した値 z̄_t に 1 Wafer の統計量を当てる。
  係数・PCA スコアは計測値の線形関数なので、z̄_t の係数・スコアは「係数・スコアの EWMA」と一致する。
  - 多項式係数（SPC）→ 係数ごとの EWMA を OR でまとめたもの
  - Mahalanobis（白色化した係数）・PCA T²（白色化したスコア）→ 多変量 EWMA（MEWMA, Lowry ほか 1992）の T²
  - PCA SPE・GPR 残差 → 平滑化した地図の再構成誤差・残差
  λ ごとの z̄_t は手法の間で共有する（SmoothedMaps）。
- scalar：1 Wafer のスコア（M3S、Mahalanobis 距離など）を正常時の平均・標準偏差で標準化し、上側の EWMA をとる。
"""
from __future__ import annotations

import numpy as np

from .base import Monitor
from .temporal import StepInput, TemporalDetector, scalar_standardizer

EWMA_MODES = ("map", "scalar")


def ewma_update(previous: np.ndarray, current: np.ndarray, lam: float) -> np.ndarray:
    return lam * current + (1.0 - lam) * previous


def ewma_filter(sequence: np.ndarray, lam: float, start: np.ndarray | float = 0.0) -> np.ndarray:
    """時系列（n × T × …）全体の EWMA（テスト・図示用）。"""
    output = np.empty_like(sequence, dtype=float)
    state = np.broadcast_to(start, sequence[:, 0].shape).astype(float)
    for t in range(sequence.shape[1]):
        state = ewma_update(state, sequence[:, t], lam)
        output[:, t] = state
    return output


class SmoothedMaps:
    """λ ごとの計測値の EWMA（n_series × 2N）。advance は新しいオブジェクトを返す（元は変えない）。"""

    def __init__(self, lambdas, center: np.ndarray, n_series: int, state: dict | None = None):
        self.lambdas = tuple(lambdas)
        self.center = center
        self.state = state if state is not None else {lam: np.tile(center, (n_series, 1)) for lam in self.lambdas}

    def advance(self, values: np.ndarray) -> "SmoothedMaps":
        new_state = {lam: ewma_update(self.state[lam], values, lam) for lam in self.lambdas}
        return SmoothedMaps(self.lambdas, self.center, len(values), new_state)

    def step(self, values: np.ndarray) -> tuple["SmoothedMaps", StepInput]:
        advanced = self.advance(values)
        return advanced, StepInput(values, advanced.state)


class EWMADetector(TemporalDetector):
    family = "M7"
    scheme = "ewma"

    def __init__(self, monitor: Monitor, lam: float, mode: str = "map"):
        if mode not in EWMA_MODES:
            raise ValueError(f"mode は {EWMA_MODES} のいずれか")
        if not 0.0 < lam <= 1.0:
            raise ValueError("λ は 0 より大きく 1 以下")
        super().__init__(monitor)
        self.mode = mode
        self.lam = float(lam) if mode == "map" else None
        self.smoothing = float(lam)
        suffix = "" if mode == "map" else "-scalar"
        self.name = f"{monitor.name}|EWMA{suffix}(λ={lam:g})"

    def fit(self, train: np.ndarray) -> "EWMADetector":
        if self.mode == "scalar":
            self.mean_, self.sd_ = scalar_standardizer(self.monitor, train)
        return self

    def init_state(self, n_series: int):
        return np.zeros(n_series) if self.mode == "scalar" else None

    def update(self, state, step: StepInput):
        if self.mode == "map":
            return None, step.score(self.monitor, self.lam)
        standardized = (step.score(self.monitor) - self.mean_) / self.sd_
        new_state = ewma_update(state, standardized, self.smoothing)
        return new_state, new_state
