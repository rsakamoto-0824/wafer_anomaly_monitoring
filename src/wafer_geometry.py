"""Wafer・Shot・Mark の座標。

座標の約束（Overlay計測ルールに合わせる）
- Wafer 中心を原点、単位は mm。Shot 座標（Xmm, Ymm）は Wafer 中心基準の絶対座標、
  Mark 座標（markXmm, markYmm）は Shot 中心基準の相対座標。解析座標は x = Xmm + markXmm, y = Ymm + markYmm。
- 有効な計測点は r < 有効半径（= Wafer 半径 − 外周除外幅）。境界上の点は含めない。
- 正規化座標は x / R_wafer, y / R_wafer（Zernike と多項式の座標）。
- Shot 番号（shotNo）は露光順（上の行から、行ごとに左右を折り返す蛇行順）、1始まり。
- Scan 方向（Direction）は露光順で 1（Up）・2（Down）を交互に割り当てる。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

EDGE_SHOT_POLICIES = ("full_shot", "all_marks_inside", "any_mark_inside")


@dataclass(frozen=True)
class PointSet:
    """計測点の集合（配列はすべて同じ長さ）。"""

    x_mm: np.ndarray
    y_mm: np.ndarray
    shot_index: np.ndarray  # layout.shots の行番号（0始まり）
    mark_no: np.ndarray  # Shot 内のマーク番号（1始まり）
    direction: np.ndarray  # Scan 方向 1 / 2
    radius_mm: float

    def __len__(self) -> int:
        return len(self.x_mm)

    @property
    def x_norm(self) -> np.ndarray:
        return self.x_mm / self.radius_mm

    @property
    def y_norm(self) -> np.ndarray:
        return self.y_mm / self.radius_mm

    @property
    def r_mm(self) -> np.ndarray:
        return np.hypot(self.x_mm, self.y_mm)

    def subset(self, index: np.ndarray) -> "PointSet":
        index = np.asarray(index)
        return PointSet(
            self.x_mm[index], self.y_mm[index], self.shot_index[index], self.mark_no[index], self.direction[index], self.radius_mm
        )


@dataclass(frozen=True)
class WaferLayout:
    radius_mm: float
    valid_radius_mm: float
    shot_size_mm: tuple[float, float]
    edge_shot_policy: str
    shots: pd.DataFrame  # shotNo, col, row, Xmm, Ymm, Radius, Direction
    mark_offsets: dict[str, np.ndarray] = field(default_factory=dict)  # 種類 → (マーク数, 2)

    @property
    def n_shots(self) -> int:
        return len(self.shots)

    def points(self, mark_kind: str) -> PointSet:
        """全 Shot の指定種類のマーク（有効なものだけ）を PointSet にする。

        any_mark_inside では外周の部分 Shot を使い、有効半径の内側のマークだけを残す。
        ほかの方針では Shot を選ぶ段階で全マークが内側にある Shot だけを残している。
        """
        offsets = self.mark_offsets[mark_kind]
        n_marks = len(offsets)
        shot_x = self.shots["Xmm"].to_numpy()
        shot_y = self.shots["Ymm"].to_numpy()
        x = (shot_x[:, None] + offsets[None, :, 0]).ravel()
        y = (shot_y[:, None] + offsets[None, :, 1]).ravel()
        shot_index = np.repeat(np.arange(self.n_shots), n_marks)
        mark_no = np.tile(np.arange(1, n_marks + 1), self.n_shots)
        direction = np.repeat(self.shots["Direction"].to_numpy(), n_marks)
        keep = np.hypot(x, y) < self.valid_radius_mm
        if self.edge_shot_policy != "any_mark_inside":
            keep = np.repeat(keep.reshape(self.n_shots, n_marks).all(axis=1), n_marks)
        return PointSet(x[keep], y[keep], shot_index[keep], mark_no[keep], direction[keep], self.radius_mm)

    def mark_table(self, points: PointSet) -> pd.DataFrame:
        """計測テーブル形式（Overlay計測ルールの項目名）の座標部分。"""
        shots = self.shots.iloc[points.shot_index]
        return pd.DataFrame(
            {
                "shotNo": shots["shotNo"].to_numpy(),
                "Direction": points.direction,
                "Xmm": shots["Xmm"].to_numpy(),
                "Ymm": shots["Ymm"].to_numpy(),
                "Radius": np.hypot(shots["Xmm"].to_numpy(), shots["Ymm"].to_numpy()),
                "markNo": points.mark_no,
                "markXmm": points.x_mm - shots["Xmm"].to_numpy(),
                "markYmm": points.y_mm - shots["Ymm"].to_numpy(),
            }
        )


def build_layout(wafer_config: dict, mark_config: dict) -> WaferLayout:
    """設定から Shot 配置と Mark 配置を作る。"""
    radius = float(wafer_config["radius_mm"])
    valid_radius = radius - float(wafer_config.get("edge_exclusion_mm", 0.0))
    pitch_x, pitch_y = (float(v) for v in wafer_config["shot_size_mm"])
    offset_x, offset_y = (float(v) for v in wafer_config.get("grid_offset_mm", [0.0, 0.0]))
    policy = wafer_config.get("edge_shot_policy", "all_marks_inside")
    if policy not in EDGE_SHOT_POLICIES:
        raise ValueError(f"edge_shot_policy は {EDGE_SHOT_POLICIES} のいずれか: {policy}")
    mark_offsets = {kind: np.asarray(values, dtype=float).reshape(-1, 2) for kind, values in mark_config.items()}
    for kind, offsets in mark_offsets.items():
        if np.any(np.abs(offsets[:, 0]) > pitch_x / 2) or np.any(np.abs(offsets[:, 1]) > pitch_y / 2):
            raise ValueError(f"{kind} のマークが Shot の外にある")

    n_cols = int(np.ceil(radius / pitch_x)) + 1
    n_rows = int(np.ceil(radius / pitch_y)) + 1
    candidates = []
    for row in range(n_rows, -n_rows - 1, -1):  # 上の行から
        for col in range(-n_cols, n_cols + 1):
            cx = offset_x + col * pitch_x
            cy = offset_y + row * pitch_y
            if _shot_is_used(cx, cy, pitch_x, pitch_y, valid_radius, mark_offsets, policy):
                candidates.append((row, col, cx, cy))

    ordered = []
    for row_number, row in enumerate(sorted({c[0] for c in candidates}, reverse=True)):
        in_row = sorted((c for c in candidates if c[0] == row), key=lambda c: c[1])
        if row_number % 2 == 1:
            in_row = in_row[::-1]  # 蛇行（2行目・4行目…は右から左）
        ordered.extend(in_row)
    shots = pd.DataFrame(ordered, columns=["row", "col", "Xmm", "Ymm"])
    shots.insert(0, "shotNo", np.arange(1, len(shots) + 1))
    shots["Radius"] = np.hypot(shots["Xmm"], shots["Ymm"])
    shots["Direction"] = np.where(np.arange(len(shots)) % 2 == 0, 1, 2)
    return WaferLayout(radius, valid_radius, (pitch_x, pitch_y), policy, shots.reset_index(drop=True), mark_offsets)


def _shot_is_used(cx, cy, pitch_x, pitch_y, valid_radius, mark_offsets, policy) -> bool:
    """Shot を使うかどうか。full_shot：Shot の四隅が有効半径内、all_marks_inside：全種類の全マークが有効半径内、
    any_mark_inside：どれか1つのマークが有効半径内（部分 Shot）。"""
    if policy == "full_shot":
        corners = np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]]) * [pitch_x / 2, pitch_y / 2]
        return bool(np.all(np.hypot(cx + corners[:, 0], cy + corners[:, 1]) < valid_radius))
    offsets = np.concatenate(list(mark_offsets.values()))
    inside = np.hypot(cx + offsets[:, 0], cy + offsets[:, 1]) < valid_radius
    return bool(np.all(inside)) if policy == "all_marks_inside" else bool(np.any(inside))
