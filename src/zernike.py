"""実数値Zernike多項式（単位円板上）。

定義（本プロジェクトの約束）
- 動径次数 n、方位次数 m（|m| ≤ n、n − |m| は偶数）。
- Z_n^m(ρ, θ) = N_n^m R_n^{|m|}(ρ) cos(mθ)   (m ≥ 0)
  Z_n^m(ρ, θ) = N_n^m R_n^{|m|}(ρ) sin(|m|θ)  (m < 0)
- R_n^m(ρ) = Σ_{s=0}^{(n−m)/2} (−1)^s (n−s)! / [s! ((n+m)/2−s)! ((n−m)/2−s)!] ρ^{n−2s}、R_n^m(1) = 1。
- 正規化（API 引数で選ぶ）：
  - "rms"  : N_n^m = sqrt(2(n+1)/(1+δ_{m0}))。円板平均で (1/π)∫ Z_j Z_k dA = δ_jk。係数は円板上の RMS [nm]。
  - "none" : N_n^m = 1（非正規化。縁 ρ = 1 での振幅が 1）。
- ρ = r / R_wafer（R_wafer = 150 mm）、θ は +x 軸から反時計回り。
- 係数の並び順は Fringe 番号（同じ k = (n+|m|)/2 の中で |m| の大きい順、cos → sin、m = 0 が最後）。
  標準の Fringe 番号は k ≤ 5（Z1〜Z36）だけに定まっている。n ≤ 7 のうち k ≥ 6 の
  (6,±6)・(7,±5)・(7,±7) は同じ並べ方を延長した番号（37〜40, 50, 51）を使い、ラベルに「*」を付ける。
- 対応表として Noll 番号（noll_index）も出力できる。
"""
from __future__ import annotations

from math import factorial

import numpy as np

NORMALIZATIONS = ("rms", "none")
STANDARD_FRINGE_MAX_GROUP = 5


def _check_mode(n: int, m: int) -> None:
    if n < 0 or abs(m) > n or (n - abs(m)) % 2 != 0:
        raise ValueError(f"不正なZernikeモード (n={n}, m={m})")


def fringe_index(n: int, m: int) -> int:
    """Fringe番号（1始まり）。例：(0,0)→1, (1,1)→2, (1,−1)→3, (2,0)→4, (4,0)→9, (6,0)→16。"""
    _check_mode(n, m)
    group = (n + abs(m)) // 2
    if m == 0:
        offset = 2 * group
    else:
        offset = 2 * (group - abs(m)) + (0 if m > 0 else 1)
    return group * group + 1 + offset


def noll_index(n: int, m: int) -> int:
    """Noll番号（1始まり）。偶数番号が cos（m > 0）、奇数番号が sin（m < 0）。"""
    _check_mode(n, m)
    first = n * (n + 1) // 2 + 1
    for j in range(first, first + n + 1):
        if noll_to_nm(j) == (n, m):
            return j
    raise AssertionError("Noll番号が見つからない")  # 到達しない


def noll_to_nm(j: int) -> tuple[int, int]:
    if j < 1:
        raise ValueError("Noll番号は1以上")
    n = 0
    while j > (n + 1) * (n + 2) // 2:
        n += 1
    k = j - n * (n + 1) // 2 - 1
    abs_m = 2 * ((k + 1) // 2) if n % 2 == 0 else 2 * (k // 2) + 1
    if abs_m == 0:
        return n, 0
    return n, abs_m if j % 2 == 0 else -abs_m


def zernike_modes(max_order: int, min_order: int = 0) -> list[tuple[int, int]]:
    """min_order ≤ n ≤ max_order の全モード (n, m) を Fringe 番号順に返す。n ≤ 7 なら36項。"""
    if max_order < 0 or min_order < 0 or min_order > max_order:
        raise ValueError("次数の範囲が不正")
    modes = [(n, m) for n in range(min_order, max_order + 1) for m in range(-n, n + 1, 2)]
    return sorted(modes, key=lambda mode: fringe_index(*mode))


def is_standard_fringe(n: int, m: int) -> bool:
    return (n + abs(m)) // 2 <= STANDARD_FRINGE_MAX_GROUP


def mode_label(n: int, m: int) -> str:
    star = "" if is_standard_fringe(n, m) else "*"
    return f"Z{fringe_index(n, m)}{star}(n={n},m={m})"


def radial_polynomial(n: int, m: int, rho: np.ndarray) -> np.ndarray:
    _check_mode(n, m)
    m = abs(m)
    rho = np.asarray(rho, dtype=float)
    result = np.zeros_like(rho)
    for s in range((n - m) // 2 + 1):
        coefficient = (-1) ** s * factorial(n - s) / (
            factorial(s) * factorial((n + m) // 2 - s) * factorial((n - m) // 2 - s)
        )
        result = result + coefficient * rho ** (n - 2 * s)
    return result


def normalization_factor(n: int, m: int, normalization: str = "rms") -> float:
    if normalization == "rms":
        return float(np.sqrt(2.0 * (n + 1) / (2.0 if m == 0 else 1.0)))
    if normalization == "none":
        return 1.0
    raise ValueError(f"normalization は {NORMALIZATIONS} のいずれか: {normalization}")


def zernike(n: int, m: int, rho: np.ndarray, theta: np.ndarray, normalization: str = "rms") -> np.ndarray:
    radial = radial_polynomial(n, m, rho)
    angular = np.cos(m * theta) if m >= 0 else np.sin(-m * theta)
    return normalization_factor(n, m, normalization) * radial * angular


def zernike_matrix(
    x_norm: np.ndarray, y_norm: np.ndarray, modes: list[tuple[int, int]], normalization: str = "rms"
) -> np.ndarray:
    """正規化座標 (x/R, y/R) で全モードを並べた行列（点数 × モード数）。"""
    x_norm = np.asarray(x_norm, dtype=float)
    y_norm = np.asarray(y_norm, dtype=float)
    rho = np.hypot(x_norm, y_norm)
    theta = np.arctan2(y_norm, x_norm)
    return np.column_stack([zernike(n, m, rho, theta, normalization) for n, m in modes])


def disk_quadrature(n_rho: int = 16, n_theta: int = 64) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """単位円板の求積点と重み（重みの合計は1＝円板平均）。

    ρ方向はガウス・ルジャンドル、θ方向は等間隔。次数 ≤ 2·n_rho − 2 の多項式を厳密に積分できる。
    """
    nodes, weights = np.polynomial.legendre.leggauss(n_rho)
    rho = 0.5 * (nodes + 1.0)
    rho_weight = weights * rho  # ∫_0^1 f ρ dρ（区間変換 0.5）を円板平均にするため ×2
    theta = 2.0 * np.pi * np.arange(n_theta) / n_theta
    rho_grid, theta_grid = np.meshgrid(rho, theta, indexing="ij")
    weight_grid = np.repeat(rho_weight[:, None], n_theta, axis=1) / n_theta
    return (rho_grid * np.cos(theta_grid)).ravel(), (rho_grid * np.sin(theta_grid)).ravel(), weight_grid.ravel()
