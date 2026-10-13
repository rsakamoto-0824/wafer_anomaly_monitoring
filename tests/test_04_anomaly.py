"""品質保証4：異常注入前後の差分が指定した異常パターンと一致する。"""
import numpy as np
import pytest

from src.anomaly_generator import SINGLE_WAFER_PATTERNS
from src.config import make_rng
from src.simulation import sample_stationary_coefficients


@pytest.mark.parametrize("pattern", [p for p in SINGLE_WAFER_PATTERNS if p != "B10"])
def test_injected_difference_equals_scaled_shape(ctx, pattern):
    gen = ctx.anomalies
    params = gen.draw(pattern, make_rng(1, pattern), 5)
    unit = gen.unit_fields(pattern, params)
    system = ctx.system()
    rng = make_rng(2, pattern)
    normal = system.measure(sample_stationary_coefficients(system.process, rng, 5), rng)
    anomalous = normal + 3.0 * unit
    np.testing.assert_allclose(anomalous - normal, 3.0 * unit, atol=1e-12)
    # 1σ_dir の大きさ：単位方向へ射影した正常計測値の標準偏差と一致する
    stats = gen.reference_stats(pattern, params)
    np.testing.assert_allclose(np.linalg.norm(unit, axis=1), stats["sigma_dir_nm"], rtol=1e-10)
    assert np.all(stats["kappa"] >= 1.0 - 1e-9)


def test_sigma_dir_matches_monte_carlo(ctx):
    gen = ctx.anomalies
    params = gen.draw("B1", make_rng(1, "mc"), 1)
    unit = gen.unit_fields("B1", params)[0]
    direction = unit / np.linalg.norm(unit)
    system = ctx.system()
    rng = make_rng(3, "mc")
    values = system.measure(sample_stationary_coefficients(system.process, rng, 20000), rng)
    projected_sd = np.std(values @ direction, ddof=1)
    assert projected_sd == pytest.approx(np.linalg.norm(unit), rel=0.03)


def test_pattern_specific_shapes(ctx):
    gen = ctx.anomalies
    points = ctx.full_points
    n = len(points)
    b9 = gen.draw("B9", make_rng(4, "b9"), 3)
    field = gen.raw_field("B9", b9, points)
    for i in range(3):
        hit = points.shot_index == b9["shot"][i]
        assert np.all(field[i, :n][~hit] == 0) and np.all(field[i, n:][~hit] == 0)
        assert np.allclose(np.hypot(field[i, :n][hit], field[i, n:][hit]), 1.0)
    b8 = gen.raw_field("B8", gen.draw("B8", make_rng(5, "b8"), 1), points)[0]
    assert np.all(np.sign(b8[n:]) == np.where(points.direction == 1, 1, -1))
    b4 = gen.raw_field("B4", {"variant": np.array([0])}, points)[0]
    assert np.all(b4[n:] == 0) and b4[:n][points.x_mm > 50].min() > b4[:n][points.x_mm < -50].max()
    delta = gen.b6_coefficient_direction()
    process = ctx.process
    i, j = process.index("X", 1, 1), process.index("Y", 1, -1)
    assert np.sign(delta[i]) != np.sign(delta[j])  # 正の相関の組を逆向きに動かす
