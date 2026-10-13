"""品質保証10・11：異常発生時刻と検出時刻の扱い、未検出系列（打ち切り）の集計。"""
import numpy as np
import pytest

from src.calibration import RecordTracker
from src.evaluation import conditional_delays, delay_summary, first_alarm_delays
from src.temporal_process import temporal_profile


def test_profiles_start_at_onset():
    params = {"ramp_length": 100, "drift_time_constant": 50, "period": 50}
    for pattern in ("A1", "A2", "A3", "A4"):
        g = temporal_profile(pattern, 300, 101, params)
        assert np.all(g[:100] == 0)
    assert temporal_profile("A1", 300, 101, params)[100] == 1.0
    assert temporal_profile("A2", 300, 101, params)[199] == pytest.approx(1.0)  # 100 枚後に振幅 a
    assert temporal_profile("A3", 300, 101, params)[100] == pytest.approx(1 - np.exp(-1 / 50))


def test_first_alarm_after_onset_and_pre_change_alarms():
    stats = np.zeros((3, 10))
    stats[0, 2] = 5  # 変化点前の誤報（時点3）
    stats[0, 6] = 5  # 変化点（時点5）から数えて3枚目
    stats[1, 4] = 5  # 変化点ちょうど → 遅延1
    delays, before = first_alarm_delays(stats, threshold=1.0, onset=5)
    assert list(delays[:2]) == [3, 1] and np.isinf(delays[2])
    assert list(before) == [1, 0, 0]


def test_censored_series_are_counted_not_dropped():
    delays = np.array([1, 2, 3, np.inf, np.inf])
    summary = delay_summary(delays, window=10)
    assert summary["detection_rate"] == pytest.approx(0.6)
    assert summary["rmst_delay"] == pytest.approx((1 + 2 + 3 + 10 + 10) / 5)
    assert summary["mean_delay_detected"] == pytest.approx(2.0)  # 参考値（未検出を除いた平均）
    assert summary["median_delay"] == pytest.approx(3.0)
    assert np.isnan(delay_summary(np.array([1, np.inf, np.inf]), 10)["median_delay"])


def test_record_tracker_matches_brute_force():
    rng = np.random.default_rng(4)
    stats = rng.standard_normal((50, 400))
    tracker = RecordTracker(50)
    for t in range(400):
        tracker.update(t + 1, stats[:, t])
    for h in (1.5, 2.5, 3.0):
        exceed = stats > h
        brute = np.where(exceed.any(axis=1), exceed.argmax(axis=1) + 1, 401)
        np.testing.assert_array_equal(tracker.run_lengths(h), brute)
    h = tracker.calibrate(50.0)
    assert tracker.average_run_length(h) >= 50.0 > tracker.average_run_length(h - 1e-3)


def test_series_with_pre_change_alarm_are_excluded_from_delay():
    delays = np.array([1.0, 5.0, np.inf, 2.0])
    before = np.array([3, 0, 0, 1])  # 1本目と4本目は変化点前に誤報（警報が続いて「遅延1」に見える）
    kept, rate = conditional_delays(delays, before)
    assert list(kept[:1]) == [5.0] and np.isinf(kept[1]) and len(kept) == 2
    assert rate == 0.5


def test_prewhitened_stream_skips_first_wafer(ctx):
    """AR(1) 残差で監視するとき、最初の Wafer（前の Wafer がない）は平均の地図として扱う。"""
    from src.config import make_rng
    from src.monitoring import M3SMonitor, ShewhartDetector
    from src.experiments.temporal_engine import TemporalSetup, iterate

    system = ctx.system(rho=0.9)
    monitor = M3SMonitor("XY")
    rng = make_rng(41, "pw")
    from src.experiments.common import training_data

    train = training_data(ctx, system, 300, "pw_test")
    monitor.fit(train)
    center = train.mean(axis=0)
    setup = TemporalSetup(system, [ShewhartDetector(monitor)], center, prewhiten_phi=0.9)
    statistics = [s for _, s in iterate(setup, rng, 5, 3)]
    expected_first = monitor.score(center[None, :])[0]
    np.testing.assert_allclose(statistics[0][:, 0], expected_first)
    assert not np.allclose(statistics[1][:, 0], expected_first)
