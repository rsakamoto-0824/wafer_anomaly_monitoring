"""正常工程の時系列変動（AR(1)）と、経時変化パターン（A1〜A4）の時間プロファイル。

正常工程： β_t − μ = ρ (β_{t−1} − μ) + η_t,  η_t ~ N(0, (1 − ρ²) Σ_β)
→ 定常共分散がちょうど Σ_β になる（イノベーション共分散を (1 − ρ²) 倍に調整）。
実装では β_t = μ + L u_t（Σ_β = L Lᵀ）とし、標準化した u_t を u_t = ρ u_{t−1} + sqrt(1 − ρ²) e_t で進める。
"""
from __future__ import annotations

import numpy as np

from .simulation import ProcessModel

TEMPORAL_PATTERNS = {
    "A1": "Step変化",
    "A2": "線形Ramp変化",
    "A3": "非線形Drift",
    "A4": "周期変動",
}


class CoefficientStream:
    """複数の系列の係数を 1 Wafer ずつ進める。最初の Wafer は定常分布から引く。"""

    def __init__(self, process: ProcessModel, rng: np.random.Generator, n_series: int):
        self.process = process
        self.rng = rng
        self.state = rng.standard_normal((n_series, len(process.mean)))
        self._started = False

    def next(self) -> np.ndarray:
        """次の Wafer の係数（n_series × 2K）。"""
        if self._started:
            rho = self.process.rho
            innovation = self.rng.standard_normal(self.state.shape)
            self.state = rho * self.state + np.sqrt(1.0 - rho * rho) * innovation
        self._started = True
        return self.process.mean + self.state @ self.process.chol.T


def coefficient_sequence(process: ProcessModel, rng: np.random.Generator, n_series: int, length: int) -> np.ndarray:
    """係数の時系列（n_series × length × 2K）。学習用の短い系列などに使う。"""
    stream = CoefficientStream(process, rng, n_series)
    return np.stack([stream.next() for _ in range(length)], axis=1)


def temporal_profile(pattern: str, length: int, onset: int, params: dict) -> np.ndarray:
    """経時変化の時間プロファイル g(t)（長さ length、t = 1..length、1始まりの onset から変化）。

    振幅 a の異常は a · σ_dir · g(t) · (単位方向) として足す。
    - A1 Step       : g = 1                                  （t ≥ onset）
    - A2 線形Ramp   : g = (t − onset + 1) / ramp_length       （ramp_length 枚後に 1、その後も同じ傾きで増える）
    - A3 非線形Drift: g = 1 − exp(−(t − onset + 1) / drift_time_constant)（立ち上がって飽和する）
    - A4 周期変動   : g = sin(2π (t − onset + 1) / period)
    """
    t = np.arange(1, length + 1, dtype=float)
    elapsed = t - onset + 1
    active = elapsed >= 1
    profile = np.zeros(length)
    if pattern == "A1":
        profile[active] = 1.0
    elif pattern == "A2":
        profile[active] = elapsed[active] / float(params["ramp_length"])
    elif pattern == "A3":
        profile[active] = 1.0 - np.exp(-elapsed[active] / float(params["drift_time_constant"]))
    elif pattern == "A4":
        profile[active] = np.sin(2.0 * np.pi * elapsed[active] / float(params["period"]))
    else:
        raise ValueError(f"未知の経時変化パターン: {pattern}")
    return profile
