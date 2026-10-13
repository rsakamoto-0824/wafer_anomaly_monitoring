"""品質保証3：乱数 Seed を固定すると結果が再現する。"""
import numpy as np

from src.config import make_rng
from src.experiments.common import training_data
from src.temporal_process import coefficient_sequence


def test_same_seed_same_data(ctx):
    system = ctx.system()
    a = training_data(ctx, system, 50, "test")
    b = training_data(ctx, system, 50, "test")
    np.testing.assert_array_equal(a, b)


def test_different_keys_give_independent_streams(ctx):
    system = ctx.system()
    a = training_data(ctx, system, 50, "test", 1)
    b = training_data(ctx, system, 50, "test", 2)
    assert not np.allclose(a, b)
    assert make_rng(1, "x").random() != make_rng(2, "x").random()


def test_ar1_stationary_covariance(ctx):
    process = ctx.process.with_rho(0.95)
    sequence = coefficient_sequence(process, make_rng(5, "ar"), 4000, 3)
    cov = np.cov(sequence[:, 2, :].T)
    np.testing.assert_allclose(np.diag(cov), np.diag(process.cov), rtol=0.08)
    lag1 = np.mean((sequence[:, 1, :] - process.mean) * (sequence[:, 0, :] - process.mean), axis=0) / np.diag(process.cov)
    assert abs(np.mean(lag1) - 0.95) < 0.02
