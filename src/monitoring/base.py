"""監視手法の共通の形。

- fit(train)：正常データ（W × 2N の計測値）で学習する。
- score(values)：1 Wafer ごとの異常スコア（大きいほど異常）。管理限界は calibration.py で正常データから決める。
- vector(values)：時系列の CUSUM に使う標準化（または白色化）した特徴ベクトル（ない手法は None）。
- theoretical_threshold(alpha)：正規分布などを仮定した理論上の管理限界（参考。ない手法は None）。
"""
from __future__ import annotations

import numpy as np
from scipy import linalg


class Monitor:
    family: str = ""
    name: str = ""

    def fit(self, train: np.ndarray) -> "Monitor":
        raise NotImplementedError

    def score(self, values: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    def vector(self, values: np.ndarray) -> np.ndarray | None:
        return None

    def theoretical_threshold(self, alpha: float) -> float | None:
        return None


def stable_cholesky(cov: np.ndarray, max_tries: int = 8) -> tuple[np.ndarray, float]:
    """共分散のコレスキー分解。正定値でなければ対角に小さな値を足して安定化する（足した量も返す）。"""
    cov = 0.5 * (cov + cov.T)
    jitter = 0.0
    scale = float(np.trace(cov)) / len(cov)
    for attempt in range(max_tries):
        try:
            return linalg.cholesky(cov + jitter * np.eye(len(cov)), lower=True), jitter
        except linalg.LinAlgError:
            jitter = scale * 10.0 ** (-10 + attempt)
    raise linalg.LinAlgError("共分散行列を安定化できない")


def whiten(chol: np.ndarray, centered: np.ndarray) -> np.ndarray:
    """L⁻¹ (x − μ) を行ごとに計算する（centered は W × p）。"""
    return linalg.solve_triangular(chol, centered.T, lower=True).T
