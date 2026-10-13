"""時系列監視の共通部品：1 時点の入力（StepInput）と、各時点で独立に判定する Shewhart 型の検出器。

時系列の検出器は update(state, step) → (新しい state, 統計量) の純粋な関数として書く
（state を書き換えないので、同じ過去の state から異常の種類ごとに何度でも続きを計算できる＝CRN）。
警報後に統計量をリセットしない。変化点より前の警報は誤報として数え、検出は変化点以降で最初の警報とする。
"""
from __future__ import annotations

import numpy as np

from .base import Monitor


class StepInput:
    """ある時点の計測値（n_series × 2N）と、λ ごとの計測値の EWMA。スコアは手法ごとに1回だけ計算する。"""

    def __init__(self, values: np.ndarray, smoothed: dict[float, np.ndarray] | None = None):
        self.values = values
        self.smoothed = smoothed or {}
        self._cache: dict = {}

    def score(self, monitor: Monitor, lam: float | None = None) -> np.ndarray:
        key = ("score", id(monitor), lam)
        if key not in self._cache:
            source = self.values if lam is None else self.smoothed[lam]
            self._cache[key] = monitor.score(source)
        return self._cache[key]

    def vector(self, monitor: Monitor) -> np.ndarray:
        key = ("vector", id(monitor))
        if key not in self._cache:
            vector = monitor.vector(self.values)
            if vector is None:
                raise ValueError(f"{monitor.name} には特徴ベクトルがない")
            self._cache[key] = vector
        return self._cache[key]


class TemporalDetector:
    """時系列の検出器の共通の形。"""

    name: str = ""
    family: str = ""
    scheme: str = ""
    lam: float | None = None  # 計測値の EWMA を使う場合の λ（SmoothedMaps で共有する）

    def __init__(self, monitor: Monitor):
        self.monitor = monitor

    def fit(self, train: np.ndarray) -> "TemporalDetector":
        return self

    def init_state(self, n_series: int):
        return None

    def update(self, state, step: StepInput):
        raise NotImplementedError


class ShewhartDetector(TemporalDetector):
    """各 Wafer を独立に判定する（1 Wafer の異常スコアそのもの）。"""

    family = "Shewhart"
    scheme = "shewhart"

    def __init__(self, monitor: Monitor):
        super().__init__(monitor)
        self.name = f"{monitor.name}|Shewhart"

    def update(self, state, step: StepInput):
        return None, step.score(self.monitor)


def scalar_standardizer(monitor: Monitor, train: np.ndarray) -> tuple[float, float]:
    """1 Wafer スコアの正常時の平均と標準偏差（スカラーの EWMA・CUSUM の標準化に使う）。"""
    scores = monitor.score(train)
    return float(scores.mean()), float(scores.std(ddof=1))
