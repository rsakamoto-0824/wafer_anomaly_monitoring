"""計測値から監視に使う特徴量を作る（多項式係数、M3S）。

多項式（監視モデル）：f(x, y) = Σ_{i+j ≤ d} c_ij x^i y^j（x, y は正規化座標 x/R, y/R）。
X・Y それぞれ最小二乗で当てはめ、係数ベクトルは [X の係数, Y の係数]（長さ 2P）。
項の並びは次数の低い順、同じ次数では x の指数の大きい順（1, x, y, x², xy, y², x³, …）。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

MIN_RESIDUAL_DOF = 5  # 当てはめに残す最小の自由度（点数 − 項数）。これ未満は「識別不能」としてスキップ
MAX_CONDITION_NUMBER = 1e8


def polynomial_terms(order: int) -> list[tuple[int, int]]:
    if order < 0:
        raise ValueError("多項式の次数は0以上")
    return [(degree - j, j) for degree in range(order + 1) for j in range(degree + 1)]


def term_label(i: int, j: int) -> str:
    parts = [f"x^{i}" if i > 1 else ("x" if i == 1 else ""), f"y^{j}" if j > 1 else ("y" if j == 1 else "")]
    return "".join(parts) or "1"


def polynomial_design(x_norm: np.ndarray, y_norm: np.ndarray, order: int) -> np.ndarray:
    x_norm = np.asarray(x_norm, dtype=float)
    y_norm = np.asarray(y_norm, dtype=float)
    return np.column_stack([x_norm**i * y_norm**j for i, j in polynomial_terms(order)])


@dataclass(frozen=True)
class Identifiability:
    n_points: int
    n_terms: int
    rank: int
    condition_number: float

    @property
    def ok(self) -> bool:
        return (
            self.rank == self.n_terms
            and self.n_points - self.n_terms >= MIN_RESIDUAL_DOF
            and self.condition_number < MAX_CONDITION_NUMBER
        )


class PolynomialFit:
    """固定した計測点での XY 多項式の最小二乗（射影行列を先に作って使い回す）。"""

    def __init__(self, x_norm: np.ndarray, y_norm: np.ndarray, order: int):
        self.order = order
        self.terms = polynomial_terms(order)
        self.design = polynomial_design(x_norm, y_norm, order)
        singular = np.linalg.svd(self.design, compute_uv=False)
        rank = int(np.sum(singular > singular[0] * 1e-12))
        cond = float(singular[0] / singular[-1]) if singular[-1] > 0 else np.inf
        self.identifiability = Identifiability(len(x_norm), len(self.terms), rank, cond)
        if not self.identifiability.ok:
            raise ValueError(f"{order}次の多項式は識別できない: {self.identifiability}")
        self.projector = np.linalg.pinv(self.design)  # P × N

    @property
    def n_terms(self) -> int:
        return len(self.terms)

    def labels(self) -> list[str]:
        return [f"{axis}:{term_label(i, j)}" for axis in ("X", "Y") for i, j in self.terms]

    def coefficients(self, values: np.ndarray) -> np.ndarray:
        """計測値（W × 2N）→ 係数（W × 2P）。"""
        n = values.shape[-1] // 2
        return np.concatenate([values[..., :n] @ self.projector.T, values[..., n:] @ self.projector.T], axis=-1)

    def fitted(self, coefficients: np.ndarray) -> np.ndarray:
        p = self.n_terms
        return np.concatenate([coefficients[..., :p] @ self.design.T, coefficients[..., p:] @ self.design.T], axis=-1)


def try_polynomial_fit(x_norm: np.ndarray, y_norm: np.ndarray, order: int) -> PolynomialFit | None:
    """識別できない（点が足りない・ランク落ち）ときは None。"""
    try:
        return PolynomialFit(x_norm, y_norm, order)
    except ValueError:
        return None


def m3s_by_axis(values: np.ndarray) -> np.ndarray:
    """M3S = |平均| + 3σ を X・Y それぞれで（W × 2）。σ は不偏標準偏差（ddof = 1）で統一する。"""
    n = values.shape[-1] // 2
    result = []
    for block in (values[..., :n], values[..., n:]):
        result.append(np.abs(block.mean(axis=-1)) + 3.0 * block.std(axis=-1, ddof=1))
    return np.stack(result, axis=-1)
