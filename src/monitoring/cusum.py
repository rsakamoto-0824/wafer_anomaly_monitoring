"""M8：CUSUM。標準化した時系列特徴量に累積和を当てる（参照値 k、管理限界 h は正常時の ARL₀ などで校正）。

- componentwise：係数ごと（標準化した z_j）の両側 CUSUM
      C⁺_t = max(0, C⁺_{t−1} + z_t − k),  C⁻_t = max(0, C⁻_{t−1} − z_t − k)
  統計量は全係数の max(C⁺, C⁻)（OR 判定）。
- vector：白色化した特徴ベクトルの多変量 CUSUM（Crosier 1988, MCUSUM）
      C_t = ||S_{t−1} + x_t||,  S_t = 0（C_t ≤ k）または (S_{t−1} + x_t)(1 − k / C_t)
  統計量は ||S_t||。
- scalar：1 Wafer のスコアを標準化した値の上側 CUSUM（正方向のみ。スコアは大きいほど異常なので）。
"""
from __future__ import annotations

import numpy as np

from .base import Monitor
from .temporal import StepInput, TemporalDetector, scalar_standardizer

CUSUM_MODES = ("componentwise", "vector", "scalar")


def cusum_two_sided_update(c_plus: np.ndarray, c_minus: np.ndarray, x: np.ndarray, k: float):
    c_plus = np.maximum(0.0, c_plus + x - k)
    c_minus = np.maximum(0.0, c_minus - x - k)
    return c_plus, c_minus


def cusum_upper_update(c: np.ndarray, x: np.ndarray, k: float) -> np.ndarray:
    return np.maximum(0.0, c + x - k)


def mcusum_update(s: np.ndarray, x: np.ndarray, k: float) -> np.ndarray:
    total = s + x
    norm = np.linalg.norm(total, axis=-1, keepdims=True)
    shrink = np.where(norm > k, 1.0 - k / np.where(norm > 0, norm, 1.0), 0.0)
    return total * shrink


class CUSUMDetector(TemporalDetector):
    family = "M8"
    scheme = "cusum"

    def __init__(self, monitor: Monitor, k: float, mode: str):
        if mode not in CUSUM_MODES:
            raise ValueError(f"mode は {CUSUM_MODES} のいずれか")
        if k < 0:
            raise ValueError("参照値 k は0以上")
        super().__init__(monitor)
        self.k = float(k)
        self.mode = mode
        self.name = f"{monitor.name}|CUSUM(k={k:g})"

    def fit(self, train: np.ndarray) -> "CUSUMDetector":
        if self.mode == "scalar":
            self.mean_, self.sd_ = scalar_standardizer(self.monitor, train)
        else:
            vector = self.monitor.vector(train[:2])
            if vector is None:
                raise ValueError(f"{self.monitor.name} には特徴ベクトルがない")
            self.dim_ = vector.shape[1]
        return self

    def init_state(self, n_series: int):
        if self.mode == "scalar":
            return np.zeros(n_series)
        if self.mode == "componentwise":
            return np.zeros((n_series, self.dim_)), np.zeros((n_series, self.dim_))
        return np.zeros((n_series, self.dim_))

    def update(self, state, step: StepInput):
        if self.mode == "scalar":
            standardized = (step.score(self.monitor) - self.mean_) / self.sd_
            new_state = cusum_upper_update(state, standardized, self.k)
            return new_state, new_state
        x = step.vector(self.monitor)
        if self.mode == "componentwise":
            c_plus, c_minus = cusum_two_sided_update(state[0], state[1], x, self.k)
            return (c_plus, c_minus), np.maximum(c_plus, c_minus).max(axis=1)
        new_state = mcusum_update(state, x, self.k)
        return new_state, np.linalg.norm(new_state, axis=1)
