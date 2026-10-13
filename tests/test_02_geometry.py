"""品質保証2：Wafer 座標と Shot・Mark 座標の整合。"""
import numpy as np

from src.wafer_geometry import build_layout

MARKS = {"alignment": [[-11.0, -14.5], [11.0, -14.5], [11.0, 14.5], [-11.0, 14.5]], "overlay": [[0.0, 0.0], [-7.0, -9.0], [7.0, -9.0], [7.0, 9.0], [-7.0, 9.0]]}


def layout(policy):
    return build_layout({"radius_mm": 150.0, "edge_exclusion_mm": 3.0, "shot_size_mm": [26.0, 33.0], "edge_shot_policy": policy}, MARKS)


def test_mark_coordinates_are_shot_center_plus_offset(ctx):
    points = ctx.full_points
    table = ctx.layout.mark_table(points)
    np.testing.assert_allclose(table["Xmm"] + table["markXmm"], points.x_mm)
    np.testing.assert_allclose(table["Ymm"] + table["markYmm"], points.y_mm)
    np.testing.assert_allclose(table["Radius"], np.hypot(table["Xmm"], table["Ymm"]))
    offsets = np.array(MARKS["alignment"])
    np.testing.assert_allclose(table[["markXmm", "markYmm"]].to_numpy(), offsets[table["markNo"].to_numpy() - 1])


def test_all_points_inside_valid_radius_and_normalized(ctx):
    points = ctx.full_points
    assert np.all(points.r_mm < ctx.layout.valid_radius_mm)
    np.testing.assert_allclose(points.x_norm, points.x_mm / 150.0)
    assert np.all(np.hypot(points.x_norm, points.y_norm) < 1.0)


def test_shot_numbering_and_scan_direction(ctx):
    shots = ctx.layout.shots
    assert list(shots["shotNo"]) == list(range(1, len(shots) + 1))
    assert set(shots["Direction"]) == {1, 2}
    assert np.all(np.diff(shots["Direction"].to_numpy()) != 0)  # 露光順で交互


def test_edge_policies():
    full = layout("full_shot")
    inside = layout("all_marks_inside")
    partial = layout("any_mark_inside")
    assert full.n_shots <= inside.n_shots <= partial.n_shots
    counts = np.bincount(inside.points("alignment").shot_index)
    assert np.all(counts == 4)
    partial_counts = np.bincount(partial.points("alignment").shot_index, minlength=partial.n_shots)
    assert partial_counts.min() >= 1 and partial_counts.min() < 4  # 外周の部分 Shot がある
