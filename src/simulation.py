"""正常Waferの面内傾向（Zernike係数）と計測値の生成。

モデル
- 潜在的な面内傾向（計測誤差を含まない真値）：
    f_x(x, y) = Σ_k a_k Z_k(x, y),   f_y(x, y) = Σ_k b_k Z_k(x, y)   （n ≤ 7 の36項 × XY）
- 係数ベクトル β = [a_1..a_K, b_1..b_K] は平均 μ（正常時の指紋）、共分散 Σ_β の正規分布。
  Σ_β = D C D：D は次数ごとの標準偏差、C は相関（物理的に結び付く係数の組と、同じモードの XY 相関）。
- 計測値 = 潜在値 + Shot 共通誤差（Shot・軸ごと）+ Mark 独立誤差（点・軸ごと）。XY 間の誤差相関も選べる。
- 計測ベクトルは 1 Wafer あたり長さ 2N：前半 N 個が X、後半 N 個が Y。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .wafer_geometry import PointSet
from .zernike import mode_label, zernike_matrix, zernike_modes

AXES = ("X", "Y")


@dataclass(frozen=True)
class ProcessModel:
    """正常工程の係数分布（Wafer 間変動）と時系列相関。"""

    modes: list[tuple[int, int]]
    normalization: str
    mean: np.ndarray  # (2K,)
    cov: np.ndarray  # (2K, 2K)
    chol: np.ndarray  # cov = chol @ chol.T
    rho: float

    @property
    def n_modes(self) -> int:
        return len(self.modes)

    def coefficient_labels(self) -> list[str]:
        return [f"{axis}:{mode_label(n, m)}" for axis in AXES for n, m in self.modes]

    def index(self, axis: str, n: int, m: int) -> int:
        return AXES.index(axis) * self.n_modes + self.modes.index((n, m))

    def basis(self, points: PointSet) -> np.ndarray:
        """計測点での Zernike 行列（N × K）。"""
        return zernike_matrix(points.x_norm, points.y_norm, self.modes, self.normalization)

    def with_rho(self, rho: float) -> "ProcessModel":
        return ProcessModel(self.modes, self.normalization, self.mean, self.cov, self.chol, float(rho))


def build_process_model(config: dict) -> ProcessModel:
    max_order = int(config["zernike_max_order"])
    normalization = config.get("normalization", "rms")
    modes = zernike_modes(max_order)
    n_modes = len(modes)
    sigma_by_order = np.asarray(config["sigma_by_order_nm"], dtype=float)
    if len(sigma_by_order) < max_order + 1:
        raise ValueError("sigma_by_order_nm は次数 0〜zernike_max_order の数だけ必要")
    high_start = int(config.get("high_order_start", max_order + 1))
    high_gain = float(config.get("high_order_gain", 1.0))
    sigma_mode = np.array([sigma_by_order[n] * (high_gain if n >= high_start else 1.0) for n, _ in modes])
    sigma = np.concatenate([sigma_mode, sigma_mode])

    model_index = {(axis, n, m): AXES.index(axis) * n_modes + modes.index((n, m)) for axis in AXES for n, m in modes}
    correlation = np.eye(2 * n_modes)
    xy_corr = float(config.get("xy_same_mode_correlation", 0.0))
    if xy_corr:
        for k in range(n_modes):
            correlation[k, n_modes + k] = correlation[n_modes + k, k] = xy_corr
    for axis_a, n_a, m_a, axis_b, n_b, m_b, value in config.get("correlated_pairs", []):
        i, j = model_index[(axis_a, n_a, m_a)], model_index[(axis_b, n_b, m_b)]
        correlation[i, j] = correlation[j, i] = float(value)
    if np.linalg.eigvalsh(correlation).min() <= 1e-9:
        raise ValueError("係数の相関行列が正定値でない（correlated_pairs を見直す）")
    cov = sigma[:, None] * correlation * sigma[None, :]

    mean = np.zeros(2 * n_modes)
    for axis, n, m, value in config.get("mean_fingerprint_nm", []):
        mean[model_index[(axis, n, m)]] = float(value)
    rho = float(config.get("rho", 0.0))
    if not 0.0 <= rho < 1.0:
        raise ValueError("rho は 0 以上 1 未満")
    return ProcessModel(modes, normalization, mean, cov, np.linalg.cholesky(cov), rho)


@dataclass(frozen=True)
class NoiseModel:
    mark_sigma_nm: float
    shot_sigma_nm: float
    xy_correlation: float = 0.0
    scale: float = 1.0

    @classmethod
    def from_config(cls, config: dict, scale: float | None = None) -> "NoiseModel":
        return cls(
            float(config["mark_sigma_nm"]),
            float(config["shot_sigma_nm"]),
            float(config.get("xy_correlation", 0.0)),
            float(config.get("scale", 1.0) if scale is None else scale),
        )

    def scaled(self, scale: float) -> "NoiseModel":
        return NoiseModel(self.mark_sigma_nm, self.shot_sigma_nm, self.xy_correlation, float(scale))

    def _xy_pairs(self, rng: np.random.Generator, shape: tuple[int, ...]) -> np.ndarray:
        """XY 相関つきの標準正規乱数（最後の軸が X, Y）。"""
        base = rng.standard_normal(shape + (2,))
        if self.xy_correlation:
            c = self.xy_correlation
            base[..., 1] = c * base[..., 0] + np.sqrt(1.0 - c * c) * base[..., 1]
        return base

    def sample(self, rng: np.random.Generator, n_wafers: int, points: PointSet, n_shots: int) -> np.ndarray:
        """計測誤差（n_wafers × 2N）。Shot 共通誤差は Wafer ごとに全 Shot 分を引き、点の Shot 番号で配る。"""
        shot_error = self.shot_sigma_nm * self._xy_pairs(rng, (n_wafers, n_shots))[:, points.shot_index, :]
        mark_error = self.mark_sigma_nm * self._xy_pairs(rng, (n_wafers, len(points)))
        error = self.scale * (shot_error + mark_error)
        return np.concatenate([error[..., 0], error[..., 1]], axis=1)

    def covariance(self, points: PointSet) -> np.ndarray:
        """計測誤差の共分散（2N × 2N）。"""
        same_shot = (points.shot_index[:, None] == points.shot_index[None, :]).astype(float)
        block = self.mark_sigma_nm**2 * np.eye(len(points)) + self.shot_sigma_nm**2 * same_shot
        xy = np.array([[1.0, self.xy_correlation], [self.xy_correlation, 1.0]])
        return self.scale**2 * np.kron(xy, block)


@dataclass
class MeasurementSystem:
    """ある計測マップ（点の集合）での、係数 → 計測値の変換。"""

    process: ProcessModel
    noise: NoiseModel
    points: PointSet
    n_shots_layout: int

    def __post_init__(self) -> None:
        self.basis = self.process.basis(self.points)  # N × K

    @property
    def n_points(self) -> int:
        return len(self.points)

    def latent(self, coefficients: np.ndarray) -> np.ndarray:
        """係数（W × 2K）→ 潜在的な面内傾向（W × 2N）。"""
        k = self.process.n_modes
        return np.concatenate([coefficients[:, :k] @ self.basis.T, coefficients[:, k:] @ self.basis.T], axis=1)

    def measure(self, coefficients: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        """係数 → 計測値（潜在値 + 計測誤差）。"""
        return self.latent(coefficients) + self.noise.sample(rng, len(coefficients), self.points, self.n_shots_layout)

    def latent_covariance(self) -> np.ndarray:
        """潜在値の Wafer 間共分散（2N × 2N）。"""
        design = np.kron(np.eye(2), self.basis)  # 2N × 2K
        return design @ self.process.cov @ design.T

    def measured_covariance(self) -> np.ndarray:
        """計測値の Wafer 間共分散（潜在 + 計測誤差、2N × 2N）。"""
        return self.latent_covariance() + self.noise.covariance(self.points)

    def measured_mean(self) -> np.ndarray:
        return self.latent(self.process.mean[None, :])[0]


def sample_stationary_coefficients(process: ProcessModel, rng: np.random.Generator, n_wafers: int) -> np.ndarray:
    """定常分布から独立に係数を引く（W × 2K）。"""
    return process.mean + rng.standard_normal((n_wafers, len(process.mean))) @ process.chol.T


def split_axes(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(…, 2N) → X (…, N), Y (…, N)。"""
    n = values.shape[-1] // 2
    return values[..., :n], values[..., n:]
