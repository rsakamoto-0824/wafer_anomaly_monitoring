"""M6：GPR 残差。正常Waferの「共通の平均面内傾向」と「Wafer ごとの個体差」と「計測誤差」を分けたモデル。

軸（X・Y）ごとに、計測値 z_w(s) を
    z_w(s) = μ(s) + u_w(s) + ε_w(s)
と分ける。
- μ(s)  ：正常Wafer共通の平均面内傾向。学習データの点ごとの平均を GPR で平滑化して推定する。
- u_w(s)：Wafer ごとの個体差（座標に依存する滑らかな変動）。共分散 k(s, s') の GP（RBF または Matérn 5/2）。
- ε_w(s)：計測誤差。Shot 共通誤差 σ_s² と Mark 独立誤差 σ_m² の階層モデル（空間自己相関は扱わない）。
超パラメータ（σ_f, ℓ, σ_s, σ_m）は正常Waferの d_w = z_w − μ を全部使った周辺尤度の最大化で決める。

スコア（d = z − μ、K = K_u + K_n）
- residual：個体差の事後平均 û = K_u K⁻¹ d を除いた残差 r = d − û = K_n K⁻¹ d の rᵀ K_n⁻¹ r。
  滑らかな個体差では説明できない「急な」ずれ（Shot・Mark 単位、Scan 依存、細かい局所変形）に反応する。
- full：dᵀ K⁻¹ d（GP の下での Mahalanobis 距離）。= ûᵀK_u⁻¹û + rᵀK_n⁻¹r で、滑らかな個体差の大きさも含む。

計測点が固定なので、行列 A（residual: K⁻¹ K_n K⁻¹、full: K⁻¹）を先に作り、1 Wafer の計算は dᵀ A d だけにする
（固定グリッドによる軽量化。点が変わるときは誘導点法などが必要になる）。
"""
from __future__ import annotations

import warnings

import numpy as np
from scipy import linalg, optimize
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel, Matern, WhiteKernel

from ..wafer_geometry import PointSet
from .base import Monitor

KERNELS = ("rbf", "matern52")
STATISTICS = ("residual", "full")
LENGTH_BOUNDS_MM = (5.0, 1000.0)
SIGMA_BOUNDS_NM = (1e-3, 1e3)


def kernel_matrix(distance_mm: np.ndarray, kind: str, variance: float, length_mm: float) -> np.ndarray:
    scaled = distance_mm / length_mm
    if kind == "rbf":
        return variance * np.exp(-0.5 * scaled**2)
    if kind == "matern52":
        r = np.sqrt(5.0) * scaled
        return variance * (1.0 + r + r * r / 3.0) * np.exp(-r)
    raise ValueError(f"kernel は {KERNELS} のいずれか")


class GPRResidualMonitor(Monitor):
    family = "M6"

    def __init__(self, points: PointSet, kernel: str = "matern52", statistic: str = "residual"):
        if kernel not in KERNELS or statistic not in STATISTICS:
            raise ValueError("kernel・statistic の指定が不正")
        self.points = points
        self.kernel = kernel
        self.statistic = statistic
        self.name = f"GPR_{kernel}_{statistic}"
        coords = np.column_stack([points.x_mm, points.y_mm])
        self._coords = coords
        self._distance = np.hypot(coords[:, None, 0] - coords[None, :, 0], coords[:, None, 1] - coords[None, :, 1])
        self._same_shot = (points.shot_index[:, None] == points.shot_index[None, :]).astype(float)

    # --------------------------------------------------------------- 学習
    def fit(self, train: np.ndarray) -> "GPRResidualMonitor":
        n = len(self.points)
        self.mean_field_ = []
        self.matrix_ = []
        self.params_ = []
        for axis in range(2):
            values = train[:, axis * n : (axis + 1) * n]
            mean_field = self._smooth_mean(values.mean(axis=0))
            deviation = values - mean_field
            scatter = deviation.T @ deviation / len(deviation)
            params = self._fit_hyperparameters(scatter)
            k_u, k_n = self._covariances(params)
            factor = linalg.cho_factor(k_u + k_n, lower=True)
            k_inv = linalg.cho_solve(factor, np.eye(n))
            matrix = k_inv @ k_n @ k_inv if self.statistic == "residual" else k_inv
            self.mean_field_.append(mean_field)
            self.matrix_.append(0.5 * (matrix + matrix.T))
            self.params_.append(params)
        return self

    def _smooth_mean(self, pointwise_mean: np.ndarray) -> np.ndarray:
        """点ごとの平均を GPR で平滑化して、共通の平均面内傾向 μ(s) を得る。"""
        base = RBF(50.0, LENGTH_BOUNDS_MM) if self.kernel == "rbf" else Matern(50.0, LENGTH_BOUNDS_MM, nu=2.5)
        kernel = ConstantKernel(1.0, (1e-4, 1e4)) * base + WhiteKernel(1e-2, (1e-8, 1e2))
        model = GaussianProcessRegressor(kernel=kernel, normalize_y=True, n_restarts_optimizer=2, random_state=0)
        with warnings.catch_warnings():
            # 平均面内傾向はとても滑らかなので、長さスケールが上限に張り付くことがある（警告は出さない）
            warnings.simplefilter("ignore")
            model.fit(self._coords, pointwise_mean)
        self.mean_kernel_ = str(model.kernel_)
        return model.predict(self._coords)

    def _covariances(self, params: dict) -> tuple[np.ndarray, np.ndarray]:
        k_u = kernel_matrix(self._distance, self.kernel, params["signal_sd"] ** 2, params["length_mm"])
        k_n = params["mark_sd"] ** 2 * np.eye(len(self.points)) + params["shot_sd"] ** 2 * self._same_shot
        return k_u, k_n

    def _fit_hyperparameters(self, scatter: np.ndarray) -> dict:
        """周辺尤度（1 Wafer あたり ½[log|K| + tr(K⁻¹ S)]）を最小化する。"""
        names = ("signal_sd", "length_mm", "shot_sd", "mark_sd")

        def unpack(theta):
            return dict(zip(names, np.exp(theta)))

        def negative_log_likelihood(theta):
            k_u, k_n = self._covariances(unpack(theta))
            try:
                factor = linalg.cho_factor(k_u + k_n, lower=True)
            except linalg.LinAlgError:
                return 1e300
            logdet = 2.0 * np.sum(np.log(np.diag(factor[0])))
            return 0.5 * (logdet + np.trace(linalg.cho_solve(factor, scatter)))

        start = np.log([np.sqrt(np.mean(np.diag(scatter))), 80.0, 0.3, 0.8])
        bounds = [np.log(SIGMA_BOUNDS_NM), np.log(LENGTH_BOUNDS_MM), np.log(SIGMA_BOUNDS_NM), np.log(SIGMA_BOUNDS_NM)]
        result = optimize.minimize(negative_log_likelihood, start, method="L-BFGS-B", bounds=bounds)
        params = unpack(result.x)
        params["nll"] = float(result.fun)
        return params

    # --------------------------------------------------------------- スコア
    def deviation(self, values: np.ndarray) -> np.ndarray:
        n = len(self.points)
        return np.concatenate([values[:, :n] - self.mean_field_[0], values[:, n:] - self.mean_field_[1]], axis=1)

    def score(self, values: np.ndarray) -> np.ndarray:
        n = len(self.points)
        total = np.zeros(len(values))
        for axis in range(2):
            d = values[:, axis * n : (axis + 1) * n] - self.mean_field_[axis]
            total += np.einsum("ij,ij->i", d @ self.matrix_[axis], d)
        return total

    def decompose(self, values: np.ndarray) -> dict[str, np.ndarray]:
        """図示用：平均面内傾向 μ、個体差 û、残差 r に分ける（各 W × 2N）。"""
        n = len(self.points)
        smooth, residual = [], []
        for axis in range(2):
            k_u, k_n = self._covariances(self.params_[axis])
            d = values[:, axis * n : (axis + 1) * n] - self.mean_field_[axis]
            weights = linalg.solve(k_u + k_n, d.T, assume_a="pos").T
            smooth.append(weights @ k_u)
            residual.append(weights @ k_n)
        mean = np.broadcast_to(np.concatenate(self.mean_field_), values.shape)
        return {"mean": mean, "smooth": np.concatenate(smooth, axis=1), "residual": np.concatenate(residual, axis=1)}
