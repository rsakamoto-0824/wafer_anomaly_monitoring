"""品質保証14：APC 補正の学習点（Alignment）と検証点（Overlay）が分離される。"""
import copy

import numpy as np

from src.config import make_rng
from src.experiments.apc import build_apc_system
from src.simulation import sample_stationary_coefficients


def test_alignment_and_overlay_points_are_disjoint(ctx, config):
    apc = copy.deepcopy(config["apc"])
    system = build_apc_system(ctx, apc, 3, 0.25, 1.0)
    a = np.column_stack([system.alignment.points.x_mm, system.alignment.points.y_mm])
    o = np.column_stack([system.overlay.points.x_mm, system.overlay.points.y_mm])
    distance = np.min(np.linalg.norm(a[:, None, :] - o[None, :, :], axis=2))
    assert distance > 1.0  # 同じ座標の点がない
    assert system.alignment.n_points < len(ctx.full_points)


def test_correction_uses_only_alignment_measurements(ctx, config):
    system = build_apc_system(ctx, copy.deepcopy(config["apc"]), 3, 0.25, 1.0)
    rng = make_rng(31, "apc")
    coefficients = sample_stationary_coefficients(system.process, rng, 5)
    alignment = system.alignment.measure(coefficients, rng)
    overlay = system.overlay.measure(coefficients, rng)
    combined = system.combine(alignment, overlay)
    changed = system.combine(alignment, overlay + 10.0)  # Overlay の値を変えても補正量は変わらない
    na = system.n_alignment
    np.testing.assert_array_equal(combined[:, :na], changed[:, :na])
    np.testing.assert_allclose(changed[:, na:] - combined[:, na:], 10.0)
    # 補正は Alignment に当てはめた多項式：多項式で表せる変位は補正後の残差に残らない
    p = system.correction.n_terms
    c = np.zeros((1, 2 * p))
    c[0, 1] = 3.0  # X の x 項
    shift_a = system.correction.fitted(c)
    shift_o = system.correction_at_overlay(c)
    np.testing.assert_allclose(system.shift(shift_a, shift_o)[0, na:], 0.0, atol=1e-9)
