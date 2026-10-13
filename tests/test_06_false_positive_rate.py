"""品質保証6：異常を入れない正常データで誤報率を評価できる（校正した限界で FPR ≈ α）。"""
import numpy as np

from src.calibration import OrCombination, empirical_threshold
from src.config import make_rng
from src.evaluation import rate_with_ci
from src.experiments.common import build_single_monitors, fit_monitors, monitor_scores, training_data
from src.simulation import sample_stationary_coefficients


def test_calibrated_thresholds_give_nominal_fpr(ctx, config):
    system = ctx.system()
    train = training_data(ctx, system, 1500, "fpr_test")
    include = {"M3S_XY", "SPC_d3", "MD_d4", "T2_raw_q95", "SPE_raw_q95", "GPR_matern52_residual"}
    monitors, _ = build_single_monitors(system.points, config["monitoring"], include=include)
    fit_monitors(monitors, train)

    def draw(key, n):
        rng = make_rng(21, key)
        return system.measure(sample_stationary_coefficients(system.process, rng, n), rng)

    cal = monitor_scores(monitors, draw("cal", 20000))
    ev = monitor_scores(monitors, draw("eval", 20000))
    alpha = 0.01
    for j in range(cal.shape[1]):
        threshold = empirical_threshold(cal[:, j], alpha)
        assert (cal[:, j] > threshold).mean() <= alpha
        result = rate_with_ci(ev[:, j] > threshold)
        assert result["ci_low"] <= alpha * 1.35 and result["ci_high"] >= alpha * 0.65
    combiner = OrCombination(list(monitors)).fit(cal)
    combined_threshold = empirical_threshold(combiner.transform(cal), alpha)
    fpr = (combiner.transform(ev) > combined_threshold).mean()
    assert 0.006 < fpr < 0.015  # OR 統合後も誤報率は α のまま
