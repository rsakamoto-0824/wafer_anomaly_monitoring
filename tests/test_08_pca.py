"""品質保証8：PCA T² と SPE が正しく計算される。"""
import numpy as np

from src.monitoring import PCAModel, PCASPEMonitor, PCAT2Monitor


def test_t2_and_spe_match_manual_computation():
    rng = np.random.default_rng(3)
    mixing = rng.standard_normal((6, 20))
    train = (rng.standard_normal((500, 6)) * [5, 4, 3, 2, 1, 0.5]) @ mixing + 0.1 * rng.standard_normal((500, 20))
    model = PCAModel(0.9, "raw").fit(train)
    t2, spe = PCAT2Monitor(model), PCASPEMonitor(model)
    test = rng.standard_normal((30, 20)) * 2
    centered = test - train.mean(axis=0)
    _, s, vt = np.linalg.svd(train - train.mean(axis=0), full_matrices=False)
    eig = s**2 / (len(train) - 1)
    k = model.k_
    assert np.cumsum(eig)[k - 1] / eig.sum() >= 0.9 > np.cumsum(eig)[k - 2] / eig.sum()
    scores = centered @ vt[:k].T
    np.testing.assert_allclose(t2.score(test), np.sum(scores**2 / eig[:k], axis=1), rtol=1e-8)
    residual = centered - scores @ vt[:k]
    np.testing.assert_allclose(spe.score(test), np.sum(residual**2, axis=1), rtol=1e-8)
    # 中心からの距離の二乗 = 部分空間内（スコア）＋ 部分空間外（SPE）
    np.testing.assert_allclose(np.sum(centered**2, axis=1), np.sum(scores**2, axis=1) + spe.score(test), rtol=1e-8)
