"""M1：M3S（|平均| + 3σ）。X・Y それぞれの M3S と、XY 統合判定。

XY 統合判定は、X・Y の M3S を正常データの平均と標準偏差で標準化し、大きい方をスコアにする
（どちらかが管理限界を超えたら異常＝OR 判定。管理限界は統合後の誤報率で決める）。
σ は不偏標準偏差（ddof = 1）で統一する。
"""
from __future__ import annotations

import numpy as np

from ..feature_extraction import m3s_by_axis
from .base import Monitor

AXIS_CHOICES = ("X", "Y", "XY")


class M3SMonitor(Monitor):
    family = "M1"

    def __init__(self, axis: str = "XY"):
        if axis not in AXIS_CHOICES:
            raise ValueError(f"axis は {AXIS_CHOICES} のいずれか")
        self.axis = axis
        self.name = f"M3S_{axis}"

    def fit(self, train: np.ndarray) -> "M3SMonitor":
        values = m3s_by_axis(train)
        self.mean_ = values.mean(axis=0)
        self.sd_ = values.std(axis=0, ddof=1)
        return self

    def standardized(self, values: np.ndarray) -> np.ndarray:
        return (m3s_by_axis(values) - self.mean_) / self.sd_

    def score(self, values: np.ndarray) -> np.ndarray:
        z = self.standardized(values)
        if self.axis == "X":
            return z[:, 0]
        if self.axis == "Y":
            return z[:, 1]
        return z.max(axis=1)
