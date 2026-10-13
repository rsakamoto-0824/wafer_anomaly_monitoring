"""品質保証12：全監視手法が同じ評価データを使う。品質保証13：学習・閾値校正・評価データが分離される。"""
import copy

import numpy as np

from src.config import make_rng
from src.experiments import phase1
from src.experiments.common import SequenceRunner, build_single_monitors, build_temporal_detectors, fit_monitors, monitor_scores, training_data


def tiny_setup(ctx, config):
    p1 = copy.deepcopy(config["phase1"])
    p1.update({"n_replicates": 20, "history_length": 5, "patterns": ["B1", "B9", "B10"], "amplitudes": [2.0, 8.0], "b10_permutations": ["mirror_x"]})
    system = ctx.system()
    train = training_data(ctx, system, 400, "tiny")
    monitors, _ = build_single_monitors(system.points, config["monitoring"], include={"M3S_XY", "MD_d4", "T2_raw_q95", "SPE_raw_q95"})
    fit_monitors(monitors, train)
    detectors = build_temporal_detectors(monitors, ["MD_d4", "SPE_raw_q95"], [0.2], [0.5], shewhart=False)
    for detector in detectors:
        detector.fit(train)
    return p1, system, train, monitors, SequenceRunner(system, detectors, train.mean(axis=0))


def test_all_methods_score_the_same_anomalous_wafers(ctx, config):
    p1, system, _, monitors, runner = tiny_setup(ctx, config)
    scores, _, _, _, _, examples = phase1._anomaly_scores(ctx, runner, monitors, p1)
    # 同じ乱数キーで正常 Wafer と異常を作り直し、全手法のスコアが1つの配列から再現できることを確かめる
    maps, states, latent, values = runner.run_history(make_rng(ctx.seed, "phase1", "anomaly_base"), 20, p1["history_length"])
    np.testing.assert_array_equal(values[:4], examples["base_measured"])
    params = ctx.anomalies.draw("B9", make_rng(ctx.seed, "phase1", "anomaly_params", "B9"), 20)
    anomalous = values + 8.0 * ctx.anomalies.unit_fields("B9", params)
    expected = np.column_stack([monitor_scores(monitors, anomalous), runner.final_statistics(maps, states, anomalous)])
    np.testing.assert_allclose(scores[1, 1], expected)
    # 振幅が違っても異常のパラメータ（位置など）は同じ：変位の向きが比例する
    d2, d8 = examples["B9_a2_displacement"], examples["B9_a8_displacement"]
    np.testing.assert_allclose(d8, 4.0 * d2)


def test_training_calibration_evaluation_are_separate(ctx, config):
    p1, system, train, monitors, runner = tiny_setup(ctx, config)
    cal = phase1._normal_block(runner, monitors, ctx.seed, "calibration", 0, 30, 5)
    ev = phase1._normal_block(runner, monitors, ctx.seed, "evaluation", 0, 30, 5)
    again = phase1._normal_block(runner, monitors, ctx.seed, "calibration", 0, 30, 5)
    np.testing.assert_array_equal(cal, again)
    assert not np.any(np.isclose(cal[:, 0][:, None], ev[:, 0][None, :], rtol=0, atol=1e-12))
    # 学習データは時系列順（AR(1)）：隣り合う Wafer の相関が正
    centered = train - train.mean(axis=0)
    lag1 = np.sum(centered[1:] * centered[:-1]) / np.sum(centered[:-1] ** 2)
    assert lag1 > 0.4
    # 校正・評価用の Wafer は学習データのどれとも一致しない
    _, _, _, values = runner.run_history(make_rng(ctx.seed, "phase1", "calibration", 0), 30, 5)
    distances = np.min(np.linalg.norm(values[:, None, :] - train[None, :, :], axis=2), axis=1)
    assert np.all(distances > 1.0)
