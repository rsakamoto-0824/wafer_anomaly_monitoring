"""M4：PCA Hotelling T²、M5：PCA SPE（Q 統計量）。

入力は「固定した計測点の XY 計測値（2N 次元）」または「多項式係数ベクトル」。
正常データで主成分を求め、累積寄与率が variance_ratio（90%・95%・99%）に達するまでの k 個を使う。
- T²  = Σ_{j ≤ k} t_j² / λ_j            （主成分の部分空間の中での異常）
- SPE = ||z − ẑ||² = ||z − μ − P Pᵀ (z − μ)||²（部分空間から外れた異常＝再構成誤差）
"""
from __future__ import annotations

import numpy as np
from scipy import stats

from ..feature_extraction import PolynomialFit
from .base import Monitor

SOURCES = ("raw", "coef")


class PCAModel:
    def __init__(self, variance_ratio: float, source: str = "raw", poly: PolynomialFit | None = None):
        if source not in SOURCES:
            raise ValueError(f"source は {SOURCES} のいずれか")
        if source == "coef" and poly is None:
            raise ValueError("source='coef' には多項式が必要")
        if not 0.0 < variance_ratio < 1.0:
            raise ValueError("variance_ratio は 0 と 1 の間")
        self.variance_ratio = variance_ratio
        self.source = source
        self.poly = poly
        self.fitted = False

    @property
    def tag(self) -> str:
        source = "raw" if self.source == "raw" else f"coef{self.poly.order}"
        return f"{source}_q{int(round(self.variance_ratio * 100))}"

    def transform(self, values: np.ndarray) -> np.ndarray:
        return values if self.source == "raw" else self.poly.coefficients(values)

    def fit(self, train: np.ndarray) -> "PCAModel":
        data = self.transform(train)
        self.mean_ = data.mean(axis=0)
        centered = data - self.mean_
        _, singular, vt = np.linalg.svd(centered, full_matrices=False)
        eigenvalues = singular**2 / (len(data) - 1)
        cumulative = np.cumsum(eigenvalues) / eigenvalues.sum()
        self.k_ = int(np.searchsorted(cumulative, self.variance_ratio) + 1)
        self.loadings_ = vt[: self.k_].T  # dim × k
        self.eigenvalues_ = eigenvalues[: self.k_]
        self.residual_eigenvalues_ = eigenvalues[self.k_ :]
        self.n_train_ = len(data)
        self.explained_ = float(cumulative[self.k_ - 1])
        self.fitted = True
        return self

    def scores(self, values: np.ndarray) -> np.ndarray:
        return (self.transform(values) - self.mean_) @ self.loadings_

    def whitened(self, values: np.ndarray) -> np.ndarray:
        return self.scores(values) / np.sqrt(self.eigenvalues_)

    def t2(self, values: np.ndarray) -> np.ndarray:
        whitened = self.whitened(values)
        return np.einsum("ij,ij->i", whitened, whitened)

    def residual(self, values: np.ndarray) -> np.ndarray:
        centered = self.transform(values) - self.mean_
        return centered - (centered @ self.loadings_) @ self.loadings_.T

    def spe(self, values: np.ndarray) -> np.ndarray:
        residual = self.residual(values)
        return np.einsum("ij,ij->i", residual, residual)


class PCAT2Monitor(Monitor):
    family = "M4"

    def __init__(self, model: PCAModel):
        self.model = model
        self.name = f"T2_{model.tag}"

    def fit(self, train: np.ndarray) -> "PCAT2Monitor":
        if not self.model.fitted:
            self.model.fit(train)
        return self

    def score(self, values: np.ndarray) -> np.ndarray:
        return self.model.t2(values)

    def vector(self, values: np.ndarray) -> np.ndarray:
        return self.model.whitened(values)

    def theoretical_threshold(self, alpha: float) -> float:
        """新しい観測値の T² の F 分布による限界：k(n−1)(n+1) / (n(n−k)) · F_{k, n−k}。"""
        k, n = self.model.k_, self.model.n_train_
        return float(k * (n - 1) * (n + 1) / (n * (n - k)) * stats.f.isf(alpha, k, n - k))


class PCASPEMonitor(Monitor):
    family = "M5"

    def __init__(self, model: PCAModel):
        self.model = model
        self.name = f"SPE_{model.tag}"

    def fit(self, train: np.ndarray) -> "PCASPEMonitor":
        if not self.model.fitted:
            self.model.fit(train)
        return self

    def score(self, values: np.ndarray) -> np.ndarray:
        return self.model.spe(values)

    def theoretical_threshold(self, alpha: float) -> float | None:
        """Box の近似 g·χ²_h（g = θ₂/θ₁, h = θ₁²/θ₂, θ_i = Σ_{j>k} λ_j^i）。"""
        rest = self.model.residual_eigenvalues_
        if len(rest) == 0:
            return None
        theta1, theta2 = rest.sum(), (rest**2).sum()
        return float(theta2 / theta1 * stats.chi2.isf(alpha, theta1**2 / theta2))
