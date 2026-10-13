"""M2：多項式係数の SPC。XY それぞれ d 次（3〜5次）の多項式を当てはめ、係数ごとに管理する。

各係数を正常データの平均・標準偏差で標準化し z_j とする。係数ごとの管理図（±L σ）を OR でまとめ、
スコア = max_j |z_j|。L は全体の誤報率（どれか1つでも超える確率）が指定値になるよう経験的に決める。
"""
from __future__ import annotations

import numpy as np
from scipy import stats

from ..feature_extraction import PolynomialFit
from .base import Monitor


class PolynomialSPCMonitor(Monitor):
    family = "M2"

    def __init__(self, poly: PolynomialFit):
        self.poly = poly
        self.name = f"SPC_d{poly.order}"

    def fit(self, train: np.ndarray) -> "PolynomialSPCMonitor":
        coefficients = self.poly.coefficients(train)
        self.mean_ = coefficients.mean(axis=0)
        self.sd_ = coefficients.std(axis=0, ddof=1)
        self.n_train_ = len(train)
        return self

    def standardized(self, values: np.ndarray) -> np.ndarray:
        return (self.poly.coefficients(values) - self.mean_) / self.sd_

    def score(self, values: np.ndarray) -> np.ndarray:
        return np.abs(self.standardized(values)).max(axis=1)

    def vector(self, values: np.ndarray) -> np.ndarray:
        return self.standardized(values)

    def theoretical_threshold(self, alpha: float) -> float:
        """Bonferroni 補正（両側、係数の数 2P）。係数間の相関は無視する。"""
        return float(stats.norm.isf(alpha / (2.0 * len(self.mean_))))
