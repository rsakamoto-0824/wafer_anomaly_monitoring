"""異常パターン（B1〜B10）と経時変化の成分の形を作り、大きさをそろえる。

大きさの基準（仕様 7.3 の正規化）
- 異常の形 v（基準マップ上の 2N 次元ベクトル）を単位方向 d = v / ||v|| にし、
  正常時の計測値（潜在 + 計測誤差）をその方向へ射影したときの標準偏差 σ_dir = sqrt(dᵀ Σ_z d) を求める。
- 振幅 a の異常は Δ = a · σ_dir · d。形は座標の関数なので、別の計測マップでも同じ物理的な大きさになる。
- 参考値として κ = sqrt((dᵀ Σ_z d)(dᵀ Σ_z⁻¹ d)) ≥ 1 も出す。方向を知っている最良の検定（尤度比）は
  Mahalanobis 長 a·κ で効くので、κ が大きい形ほど相関構造を使う手法で見つけやすい。

B10（平均・標準偏差が変わらない異常）は計測値の集計値を保つ特別な処理（b10_reshape・b10_permute）。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .simulation import AXES, MeasurementSystem, ProcessModel
from .wafer_geometry import PointSet, WaferLayout
from .zernike import zernike_matrix, zernike_modes

SINGLE_WAFER_PATTERNS = {
    "B1": "Radial方向の異常",
    "B2": "Tangential方向の異常",
    "B3": "局所的な変形",
    "B4": "左右・上下非対称",
    "B5": "高次Zernike成分異常",
    "B6": "複数係数の異常な組み合わせ",
    "B7": "監視モデル次数で表現できない異常",
    "B8": "Scan Up/Down依存異常",
    "B9": "単一Shot異常",
    "B10": "平均・分散が変わらない面内形状異常",
}
SHAPE_DESCRIPTIONS = {
    "B1": "動径方向の変位 h(ρ)=ρ³（外周ほど大きい3次の放射状歪み）",
    "B2": "接線方向の変位 h(ρ)=ρ³（外周ほど大きい回転）",
    "B3": "ガウス形の局所変形（中心は半径0.3R〜0.85Rで無作為、幅20 mm、向きは無作為）",
    "B4": "片側だけの倍率変化（右・左・上・下のどれか。滑らかな max(u, 0)）",
    "B5": "動径次数 n=4〜5 の Zernike の無作為な組み合わせ（5次多項式で表せる、3次では表せない）",
    "B6": "相関する係数の組（等方倍率・回転・3次放射）を相関と逆向きに動かす",
    "B7": "動径次数 n=8〜9 の Zernike の無作為な組み合わせ（監視多項式でも正常モデルでも表せない）",
    "B8": "Scan 方向（Up/Down）で符号が変わる一定のずれ（X 0.3 : Y 1）",
    "B9": "無作為に選んだ1 Shot の全マークが同じ向きにずれる",
    "B10": "平均・標準偏差を保ったまま、正常な指紋の一部を滑らかな形（n=2〜4 の Zernike）に置き換える",
}
TEMPORAL_COMPONENTS = {
    "low": "低次Zernike成分（X: Z(2,2), Y: Z(2,−2)）",
    "high": "高次Zernike成分（X: Z(5,1), Y: Z(5,−1)）",
    "radial": "Radial成分（B1 と同じ形）",
    "tangential": "Tangential成分（B2 と同じ形）",
    "asymmetric": "非対称成分（右側だけの X 倍率、B4 の1種類）",
    "local": "局所変形成分（中心 (70.7, 70.7) mm、外向き、幅20 mm）",
}


@dataclass(frozen=True)
class AnomalySettings:
    local_width_mm: float = 20.0
    local_radius_range: tuple[float, float] = (0.3, 0.85)
    asymmetry_softness: float = 0.1
    b5_orders: tuple[int, ...] = (4, 5)
    b7_orders: tuple[int, ...] = (8, 9)
    b10_orders: tuple[int, ...] = (2, 3, 4)
    scan_vector: tuple[float, float] = (0.3, 1.0)
    b9_level: str = "shot"  # shot | mark

    @classmethod
    def from_config(cls, config: dict) -> "AnomalySettings":
        values = {key: tuple(value) if isinstance(value, list) else value for key, value in config.items()}
        return cls(**values)


class AnomalyGenerator:
    """異常の形を作り、基準マップ上の σ_dir で「1σ の異常」にそろえる。"""

    def __init__(self, process: ProcessModel, layout: WaferLayout, reference: MeasurementSystem, settings: AnomalySettings):
        self.process = process
        self.layout = layout
        self.reference = reference
        self.settings = settings
        self._ref_cov = reference.measured_covariance()
        self._ref_chol = np.linalg.cholesky(self._ref_cov)

    # ------------------------------------------------------------------ 乱数で決めるパラメータ
    def draw(self, pattern: str, rng: np.random.Generator, n: int) -> dict:
        """パターンの無作為なパラメータ（振幅によらない。CRN のため振幅ごとに引き直さない）。"""
        s = self.settings
        if pattern == "B3":
            lo, hi = s.local_radius_range
            radius = self.layout.radius_mm * np.sqrt(rng.uniform(lo**2, hi**2, n))
            angle = rng.uniform(0, 2 * np.pi, n)
            return {"cx": radius * np.cos(angle), "cy": radius * np.sin(angle), "phi": rng.uniform(0, 2 * np.pi, n)}
        if pattern == "B4":
            return {"variant": rng.integers(0, 4, n)}
        if pattern in ("B5", "B7", "B10"):
            orders = {"B5": s.b5_orders, "B7": s.b7_orders, "B10": s.b10_orders}[pattern]
            modes = [mode for order in orders for mode in zernike_modes(order, order)]
            return {"modes": modes, "coef": rng.standard_normal((n, 2, len(modes)))}
        if pattern == "B6":
            return {"sign": rng.choice([-1.0, 1.0], n)}
        if pattern == "B9":
            # 基準マップに載っている Shot（mark 単位なら点）から一様に選ぶ
            ref = self.reference.points
            if s.b9_level == "mark":
                pick = rng.integers(0, len(ref), n)
                shot, mark = ref.shot_index[pick], ref.mark_no[pick]
            else:
                shot = rng.choice(np.unique(ref.shot_index), n)
                mark = np.zeros(n, dtype=int)
            return {"shot": shot, "mark": mark, "phi": rng.uniform(0, 2 * np.pi, n)}
        return {"n": n}

    # ------------------------------------------------------------------ 形（物理量の比だけが意味を持つ）
    def raw_field(self, pattern: str, params: dict, points: PointSet) -> np.ndarray:
        """異常の形（n × 2N）。大きさはまだそろえていない。"""
        n = self._count(params)
        xn, yn = points.x_norm, points.y_norm
        zeros = np.zeros((n, len(points)))
        if pattern in ("B1", "radial"):
            rho2 = xn**2 + yn**2
            return np.concatenate([np.broadcast_to(rho2 * xn, (n, len(points))), np.broadcast_to(rho2 * yn, (n, len(points)))], axis=1)
        if pattern in ("B2", "tangential"):
            rho2 = xn**2 + yn**2
            return np.concatenate([np.broadcast_to(-rho2 * yn, (n, len(points))), np.broadcast_to(rho2 * xn, (n, len(points)))], axis=1)
        if pattern == "B3":
            return self._local(points, params["cx"], params["cy"], params["phi"])
        if pattern == "local":
            c = 100.0 / np.sqrt(2.0)
            return self._local(points, np.full(n, c), np.full(n, c), np.full(n, np.pi / 4))
        if pattern == "B4":
            return self._asymmetry(points, params["variant"])
        if pattern == "asymmetric":
            return self._asymmetry(points, np.zeros(n, dtype=int))
        if pattern in ("B5", "B7", "B10"):
            basis = zernike_matrix(xn, yn, params["modes"], self.process.normalization)
            return np.concatenate([params["coef"][:, 0, :] @ basis.T, params["coef"][:, 1, :] @ basis.T], axis=1)
        if pattern in ("low", "high"):
            (n_x, m_x), (n_y, m_y) = ((2, 2), (2, -2)) if pattern == "low" else ((5, 1), (5, -1))
            bx = zernike_matrix(xn, yn, [(n_x, m_x)], self.process.normalization)[:, 0]
            by = zernike_matrix(xn, yn, [(n_y, m_y)], self.process.normalization)[:, 0]
            return np.concatenate([np.broadcast_to(bx, (n, len(points))), np.broadcast_to(by, (n, len(points)))], axis=1)
        if pattern == "B6":
            delta = self.b6_coefficient_direction()
            field = MeasurementSystem(self.process, self.reference.noise, points, self.layout.n_shots).latent(delta[None, :])
            return params["sign"][:, None] * field
        if pattern == "B8":
            sign = np.where(points.direction == 1, 1.0, -1.0)
            vx, vy = self.settings.scan_vector
            return np.concatenate([np.broadcast_to(vx * sign, (n, len(points))), np.broadcast_to(vy * sign, (n, len(points)))], axis=1)
        if pattern == "B9":
            hit = points.shot_index[None, :] == params["shot"][:, None]
            if self.settings.b9_level == "mark":
                hit &= points.mark_no[None, :] == params["mark"][:, None]
            return np.concatenate([hit * np.cos(params["phi"])[:, None], hit * np.sin(params["phi"])[:, None]], axis=1)
        raise ValueError(f"未知の異常パターン: {pattern}")

    def b6_coefficient_direction(self) -> np.ndarray:
        """B6：相関する係数の組を、相関と逆向きに（各係数の標準偏差の大きさで）動かす係数ベクトル。"""
        delta = np.zeros(len(self.process.mean))
        sigma = np.sqrt(np.diag(self.process.cov))
        corr = self.process.cov / np.outer(sigma, sigma)
        k = self.process.n_modes
        for i in range(2 * k):
            for j in range(i + 1, 2 * k):
                if abs(corr[i, j]) > 0.05:
                    delta[i] += sigma[i]
                    delta[j] -= np.sign(corr[i, j]) * sigma[j]
        if not np.any(delta):
            raise ValueError("B6 には相関する係数の組（correlated_pairs）が必要")
        return delta

    def _local(self, points: PointSet, cx: np.ndarray, cy: np.ndarray, phi: np.ndarray) -> np.ndarray:
        width = self.settings.local_width_mm
        dist2 = (points.x_mm[None, :] - cx[:, None]) ** 2 + (points.y_mm[None, :] - cy[:, None]) ** 2
        bump = np.exp(-dist2 / (2.0 * width**2))
        return np.concatenate([bump * np.cos(phi)[:, None], bump * np.sin(phi)[:, None]], axis=1)

    def _asymmetry(self, points: PointSet, variant: np.ndarray) -> np.ndarray:
        eps = self.settings.asymmetry_softness

        def soft_positive(u):
            return 0.5 * (u + np.sqrt(u * u + eps * eps))

        xn, yn = points.x_norm[None, :], points.y_norm[None, :]
        v = variant[:, None]
        dx = np.where(v == 0, soft_positive(xn), np.where(v == 1, -soft_positive(-xn), 0.0))
        dy = np.where(v == 2, soft_positive(yn), np.where(v == 3, -soft_positive(-yn), 0.0))
        return np.concatenate([dx, dy], axis=1)

    @staticmethod
    def _count(params: dict) -> int:
        for key in ("cx", "variant", "coef", "sign", "shot"):
            if key in params:
                return len(params[key])
        return int(params["n"])

    # ------------------------------------------------------------------ 大きさをそろえる
    def reference_stats(self, pattern: str, params: dict) -> dict[str, np.ndarray]:
        """基準マップ上の σ_dir（nm）、κ、形のノルムなど（各 n 個）。"""
        v = self.raw_field(pattern, params, self.reference.points)
        norm = np.linalg.norm(v, axis=1)
        if np.any(norm <= 0):
            raise ValueError(f"{pattern}：基準マップ上で形がゼロ（計測点に掛からない）")
        d = v / norm[:, None]
        sigma_dir = np.sqrt(np.einsum("ij,jk,ik->i", d, self._ref_cov, d))
        whitened = np.linalg.solve(self._ref_chol, d.T).T  # L⁻¹ d
        kappa = sigma_dir * np.linalg.norm(whitened, axis=1)
        return {"sigma_dir_nm": sigma_dir, "kappa": kappa, "raw_norm": norm}

    def unit_fields(self, pattern: str, params: dict, points: PointSet | None = None) -> np.ndarray:
        """振幅 a = 1（= 1σ_dir）の異常（n × 2N、nm）。points を省くと基準マップで返す。"""
        stats = self.reference_stats(pattern, params)
        scale = stats["sigma_dir_nm"] / stats["raw_norm"]
        points = self.reference.points if points is None else points
        return scale[:, None] * self.raw_field(pattern, params, points)


# ---------------------------------------------------------------------- B10：平均・標準偏差を保つ異常
def b10_reshape(measured: np.ndarray, latent: np.ndarray, shape: np.ndarray, amplitude: float) -> tuple[np.ndarray, np.ndarray]:
    """方法2：計測値の平均と標準偏差を X・Y それぞれで保ったまま、滑らかな面内形状だけを変える。

    計測誤差には手を付けず、滑らかな成分だけを動かす。軸ごとに、
        Δ = t·u − s·c_s
    とする。u は異常の形（平均0、ノルム1）、c_s は真の潜在値（滑らかな面内傾向）を中心化したもの、
    t は異常の大きさ（amplitude × 形の 1σ_dir のノルム）。s は「中心化した計測値 c のノルムが変わらない」
        ||c + Δ||² = ||c||²  ⇔  ||c_s||² s² − 2(⟨c, c_s⟩ + t⟨u, c_s⟩) s + (2t⟨c, u⟩ + t²) = 0
    の解のうち絶対値の小さい方。Δ の平均は0なので平均も変わらない。つまり「正常な指紋の一部が異常な形に
    置き換わり、ばらつきの総量は同じ」という変形になる。解がないほど t が大きいときは、解がある最大の t に抑える。
    戻り値は（変形後の計測値、t を抑えたかどうか（Wafer × 軸））。
    """
    result = measured.copy()
    n = measured.shape[1] // 2
    capped = np.zeros((len(measured), 2), dtype=bool)
    for axis in range(2):
        block = slice(axis * n, (axis + 1) * n)
        values = measured[:, block]
        centered = values - values.mean(axis=1, keepdims=True)
        smooth = latent[:, block] - latent[:, block].mean(axis=1, keepdims=True)
        u = shape[:, block] - shape[:, block].mean(axis=1, keepdims=True)
        u = u / np.linalg.norm(u, axis=1, keepdims=True)
        target = amplitude * np.linalg.norm(shape[:, block], axis=1)
        a = np.einsum("ij,ij->i", smooth, smooth)
        c_s = np.einsum("ij,ij->i", centered, smooth)
        u_s = np.einsum("ij,ij->i", u, smooth)
        c_u = np.einsum("ij,ij->i", centered, u)

        t = target.copy()
        infeasible = _b10_discriminant(t, c_s, u_s, a, c_u) < 0
        if np.any(infeasible):
            low, high = np.zeros(infeasible.sum()), target[infeasible]
            for _ in range(60):  # 解がある最大の t を二分探索（t = 0 では必ず解がある）
                middle = 0.5 * (low + high)
                ok = _b10_discriminant(middle, c_s[infeasible], u_s[infeasible], a[infeasible], c_u[infeasible]) >= 0
                low = np.where(ok, middle, low)
                high = np.where(ok, high, middle)
            t[infeasible] = low
            capped[infeasible, axis] = True
        b = c_s + t * u_s
        root = np.sqrt(np.maximum(_b10_discriminant(t, c_s, u_s, a, c_u), 0.0))
        s_candidates = np.stack([(b - root) / a, (b + root) / a])
        s = s_candidates[np.argmin(np.abs(s_candidates), axis=0), np.arange(len(a))]
        result[:, block] = values + t[:, None] * u - s[:, None] * smooth
    return result, capped


def _b10_discriminant(t, c_s, u_s, a, c_u):
    """b10_reshape の s についての2次方程式の判別式（/4）。"""
    return (c_s + t * u_s) ** 2 - a * (2 * t * c_u + t * t)


B10_PERMUTATIONS = {
    "rot180": "180°回転した位置へ値を移す",
    "mirror_x": "左右反転（x → −x）した位置へ値を移す",
    "mirror_y": "上下反転（y → −y）した位置へ値を移す",
    "shuffle": "全点の位置を無作為に入れ替える",
}


def symmetric_permutation(points: PointSet, kind: str, tol_mm: float = 1e-6) -> np.ndarray:
    """点 i の値を移す元の点の番号 perm[i]（z'[i] = z[perm[i]]）。マップが対称でないとエラー。"""
    sx, sy = {"rot180": (-1, -1), "mirror_x": (-1, 1), "mirror_y": (1, -1)}[kind]
    target_x, target_y = sx * points.x_mm, sy * points.y_mm
    dist = np.hypot(target_x[:, None] - points.x_mm[None, :], target_y[:, None] - points.y_mm[None, :])
    perm = dist.argmin(axis=1)
    if np.any(dist[np.arange(len(points)), perm] > tol_mm):
        raise ValueError(f"計測マップが {kind} について対称でない")
    return perm


def b10_permute(measured: np.ndarray, points: PointSet, kind: str, rng: np.random.Generator | None = None) -> np.ndarray:
    """方法1：計測値の集合はそのまま、位置だけを入れ替える（X・Y の値の組を一緒に動かす）。"""
    n = len(points)
    if kind == "shuffle":
        if rng is None:
            raise ValueError("shuffle には rng が必要")
        perm = np.argsort(rng.random((len(measured), n)), axis=1)
    else:
        perm = np.broadcast_to(symmetric_permutation(points, kind), (len(measured), n))
    rows = np.arange(len(measured))[:, None]
    return np.concatenate([measured[:, :n][rows, perm], measured[:, n:][rows, perm]], axis=1)


def anomaly_size_summary(fields: np.ndarray) -> dict[str, float]:
    """異常の物理的な大きさ（nm）：計測点での RMS（X・Y の点ごとの大きさ）と最大値。"""
    n = fields.shape[1] // 2
    magnitude = np.hypot(fields[:, :n], fields[:, n:])
    return {"rms_nm": float(np.sqrt(np.mean(magnitude**2))), "max_nm": float(magnitude.max(axis=1).mean())}


__all__ = [
    "AXES",
    "AnomalyGenerator",
    "AnomalySettings",
    "B10_PERMUTATIONS",
    "SHAPE_DESCRIPTIONS",
    "SINGLE_WAFER_PATTERNS",
    "TEMPORAL_COMPONENTS",
    "anomaly_size_summary",
    "b10_permute",
    "b10_reshape",
    "symmetric_permutation",
]
