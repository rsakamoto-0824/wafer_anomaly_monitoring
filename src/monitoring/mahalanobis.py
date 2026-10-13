"""M3：多項式係数ベクトルの Mahalanobis 距離 D² = (β − μ)ᵀ Σ⁻¹ (β − μ)。

Σ は縮小推定（既定は Ledoit–Wolf）で安定化する。それでも正定値でなければ対角に小さな値を足す。
"""
from __future__ import annotations

import numpy as np
from scipy import stats
from sklearn.covariance import OAS, EmpiricalCovariance, LedoitWolf

from ..feature_extraction import PolynomialFit
from .base import Monitor, stable_cholesky, whiten

SHRINKAGE_METHODS = {"ledoit_wolf": LedoitWolf, "oas": OAS, "empirical": EmpiricalCovariance}


class MahalanobisMonitor(Monitor):
    family = "M3"

    def __init__(self, poly: PolynomialFit, shrinkage: str = "ledoit_wolf"):
        if shrinkage not in SHRINKAGE_METHODS:
            raise ValueError(f"shrinkage は {tuple(SHRINKAGE_METHODS)} のいずれか")
        self.poly = poly
        self.shrinkage = shrinkage
        self.name = f"MD_d{poly.order}"

    def fit(self, train: np.ndarray) -> "MahalanobisMonitor":
        coefficients = self.poly.coefficients(train)
        self.mean_ = coefficients.mean(axis=0)
        estimator = SHRINKAGE_METHODS[self.shrinkage]().fit(coefficients)
        self.cov_ = estimator.covariance_
        self.shrinkage_ = float(getattr(estimator, "shrinkage_", 0.0))
        self.chol_, self.jitter_ = stable_cholesky(self.cov_)
        return self

    def whitened(self, values: np.ndarray) -> np.ndarray:
        return whiten(self.chol_, self.poly.coefficients(values) - self.mean_)

    def score(self, values: np.ndarray) -> np.ndarray:
        whitened = self.whitened(values)
        return np.einsum("ij,ij->i", whitened, whitened)

    def vector(self, values: np.ndarray) -> np.ndarray:
        return self.whitened(values)

    def theoretical_threshold(self, alpha: float) -> float:
        """χ² 分布（自由度 2P）。推定誤差と縮小は考えない漸近近似。"""
        return float(stats.chi2.isf(alpha, len(self.mean_)))
