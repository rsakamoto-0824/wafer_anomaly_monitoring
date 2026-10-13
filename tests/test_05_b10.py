"""品質保証5：B10 で平均・標準偏差・M3S が一致する。"""
import numpy as np
import pytest

from src.anomaly_generator import B10_PERMUTATIONS, b10_permute, b10_reshape
from src.config import make_rng
from src.feature_extraction import m3s_by_axis
from src.simulation import sample_stationary_coefficients, split_axes

TOL_NM = 1e-9


def normal_wafers(ctx, n=200):
    system = ctx.system()
    rng = make_rng(11, "b10")
    latent = system.latent(sample_stationary_coefficients(system.process, rng, n))
    return latent, latent + system.noise.sample(rng, n, system.points, ctx.layout.n_shots)


def assert_same_summary(before, after):
    for b, a in zip(split_axes(before), split_axes(after)):
        np.testing.assert_allclose(a.mean(axis=1), b.mean(axis=1), atol=TOL_NM)
        np.testing.assert_allclose(a.std(axis=1, ddof=1), b.std(axis=1, ddof=1), atol=TOL_NM)
    np.testing.assert_allclose(m3s_by_axis(after), m3s_by_axis(before), atol=TOL_NM)


@pytest.mark.parametrize("amplitude", [1.0, 4.0, 16.0])
def test_smooth_reshape_keeps_mean_sd_m3s(ctx, amplitude):
    latent, values = normal_wafers(ctx)
    params = ctx.anomalies.draw("B10", make_rng(12, "b10"), len(values))
    shape = ctx.anomalies.unit_fields("B10", params)
    reshaped, capped = b10_reshape(values, latent, shape, amplitude)
    assert_same_summary(values, reshaped)
    assert np.sqrt(np.mean((reshaped - values) ** 2)) > 0.1  # 形は変わっている
    # 計測誤差（計測値 − 潜在値）には手を付けない：変化は滑らかな成分（形と潜在値の組み合わせ）だけ
    change = reshaped - values
    n = values.shape[1] // 2
    for axis in range(2):
        block = slice(axis * n, (axis + 1) * n)
        for i in range(3):
            design = np.column_stack([np.ones(n), shape[i, block], latent[i, block]])
            coef, *_ = np.linalg.lstsq(design, change[i, block], rcond=None)
            np.testing.assert_allclose(design @ coef, change[i, block], atol=1e-8)


@pytest.mark.parametrize("kind", list(B10_PERMUTATIONS))
def test_permutation_keeps_multiset_exactly(ctx, kind):
    _, values = normal_wafers(ctx, 50)
    permuted = b10_permute(values, ctx.full_points, kind, make_rng(13, kind))
    for b, a in zip(split_axes(values), split_axes(permuted)):
        np.testing.assert_array_equal(np.sort(a, axis=1), np.sort(b, axis=1))
    assert_same_summary(values, permuted)
    assert not np.allclose(permuted, values)
