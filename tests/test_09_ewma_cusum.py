"""品質保証9：EWMA と CUSUM の更新式。"""
import numpy as np

from src.monitoring.cusum import cusum_two_sided_update, cusum_upper_update, mcusum_update
from src.monitoring.ewma import ewma_filter, ewma_update


def test_ewma_recursion():
    x = np.array([[1.0, 2.0, 0.0, -1.0]])
    lam = 0.2
    expected, s = [], 0.0
    for value in x[0]:
        s = lam * value + (1 - lam) * s
        expected.append(s)
    np.testing.assert_allclose(ewma_filter(x, lam)[0], expected)
    assert ewma_update(np.array([1.0]), np.array([3.0]), 0.5)[0] == 2.0


def test_cusum_updates():
    c_plus, c_minus = np.zeros(2), np.zeros(2)
    for value in ([1.0, -1.0], [2.0, -2.0], [-0.2, 0.2]):
        c_plus, c_minus = cusum_two_sided_update(c_plus, c_minus, np.array(value), 0.5)
    np.testing.assert_allclose(c_plus, [max(0, max(0, 0.5) + 1.5 - 0.7), 0.0])
    np.testing.assert_allclose(c_minus, [0.0, max(0, 0.5 + 1.5 - 0.7)])
    assert cusum_upper_update(np.array([0.2]), np.array([-1.0]), 0.5)[0] == 0.0
    assert cusum_upper_update(np.array([0.2]), np.array([1.0]), 0.5)[0] == 0.7


def test_crosier_mcusum():
    s = np.zeros((1, 2))
    s = mcusum_update(s, np.array([[3.0, 4.0]]), 1.0)  # ||x|| = 5 → (1 − 1/5) x
    np.testing.assert_allclose(s, [[2.4, 3.2]])
    s = mcusum_update(np.zeros((1, 2)), np.array([[0.3, 0.4]]), 1.0)  # ||x|| = 0.5 ≤ k → 0
    np.testing.assert_allclose(s, [[0.0, 0.0]])
