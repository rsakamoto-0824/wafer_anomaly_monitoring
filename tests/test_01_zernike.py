"""品質保証1：Zernike 多項式の次数・正規化。"""
import numpy as np
import pytest

from src.zernike import (
    disk_quadrature,
    fringe_index,
    noll_index,
    noll_to_nm,
    radial_polynomial,
    zernike_matrix,
    zernike_modes,
)


def test_mode_count_up_to_order_7():
    modes = zernike_modes(7)
    assert len(modes) == 36
    assert all(n <= 7 and (n - abs(m)) % 2 == 0 for n, m in modes)


def test_rms_normalized_modes_are_orthonormal_on_unit_disk():
    x, y, w = disk_quadrature(n_rho=20, n_theta=80)
    basis = zernike_matrix(x, y, zernike_modes(9))
    gram = basis.T @ (w[:, None] * basis)
    np.testing.assert_allclose(gram, np.eye(len(gram)), atol=1e-10)


def test_unnormalized_modes_have_unit_edge_value():
    for n, m in zernike_modes(7):
        assert radial_polynomial(n, m, np.array([1.0]))[0] == pytest.approx(1.0)
    edge = zernike_matrix(np.array([1.0]), np.array([0.0]), [(4, 0)], "none")
    assert edge[0, 0] == pytest.approx(1.0)


@pytest.mark.parametrize("mode,fringe,noll", [((0, 0), 1, 1), ((1, 1), 2, 2), ((1, -1), 3, 3), ((2, 0), 4, 4), ((2, 2), 5, 6), ((2, -2), 6, 5), ((3, 1), 7, 8), ((4, 0), 9, 11), ((6, 0), 16, 22)])
def test_fringe_and_noll_indices(mode, fringe, noll):
    assert fringe_index(*mode) == fringe
    assert noll_index(*mode) == noll
    assert noll_to_nm(noll) == mode


def test_explicit_low_order_forms():
    x = np.array([0.3, -0.5, 0.1])
    y = np.array([0.2, 0.4, -0.7])
    z = zernike_matrix(x, y, [(1, 1), (1, -1), (2, 0)])
    np.testing.assert_allclose(z[:, 0], 2 * x, atol=1e-12)
    np.testing.assert_allclose(z[:, 1], 2 * y, atol=1e-12)
    np.testing.assert_allclose(z[:, 2], np.sqrt(3) * (2 * (x * x + y * y) - 1), atol=1e-12)
