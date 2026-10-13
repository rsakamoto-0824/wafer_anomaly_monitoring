"""品質保証7：Mahalanobis 距離が数値的に安定して計算できる。"""
import numpy as np

from src.feature_extraction import PolynomialFit
from src.monitoring import MahalanobisMonitor
from src.monitoring.base import stable_cholesky, whiten


def test_matches_direct_formula_when_well_conditioned():
    rng = np.random.default_rng(0)
    cov = np.array([[2.0, 0.6, 0.0], [0.6, 1.0, 0.3], [0.0, 0.3, 0.5]])
    chol, jitter = stable_cholesky(cov)
    assert jitter == 0.0
    x = rng.standard_normal((10, 3))
    direct = np.einsum("ij,jk,ik->i", x, np.linalg.inv(cov), x)
    w = whiten(chol, x)
    np.testing.assert_allclose(np.sum(w * w, axis=1), direct, rtol=1e-10)


def test_singular_covariance_is_stabilized():
    rng = np.random.default_rng(1)
    base = rng.standard_normal((50, 2))
    singular = np.cov(np.column_stack([base, base[:, 0] + base[:, 1]]).T)  # ランク2
    chol, jitter = stable_cholesky(singular)
    assert np.all(np.isfinite(chol)) and jitter >= 0.0


def test_monitor_with_few_training_wafers_is_finite():
    rng = np.random.default_rng(2)
    x = rng.uniform(-0.9, 0.9, 120)
    y = rng.uniform(-0.9, 0.9, 120)
    poly = PolynomialFit(x, y, 5)  # 42 係数
    train = rng.standard_normal((30, 240))  # 学習 Wafer が係数より少ない
    monitor = MahalanobisMonitor(poly).fit(train)
    scores = monitor.score(rng.standard_normal((20, 240)))
    assert np.all(np.isfinite(scores)) and np.all(scores >= 0)
    assert 0.0 < monitor.shrinkage_ <= 1.0
