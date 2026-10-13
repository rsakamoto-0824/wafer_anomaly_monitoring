"""時系列（経時変化）の評価の共通エンジン：ARL₀ の校正・確認と、変化を入れた系列での検出遅延。

- 正常系列は seed と用途キーから作るので、異常の種類・振幅・検出器によらず同じ正常系列になる（CRN）。
- 管理限界は正常系列（長さ L、n_runs 本）の連長から、ARL₀ が目標値になるよう二分探索で決める。
- 変化を入れた系列では、変化点 onset 以降で最初に警報が出た時点から遅延を求める。変化点より前に警報が出た系列は
  誤報として数え、遅延の集計から除く（条件付き期待遅延。前の警報が変化点以降まで続いて「すぐ検出」に見えるのを防ぐ）。
- 比べる基準として、変化を入れない系列（amplitude = 0、pattern = "no_change"）でも同じ集計をする。
- prewhiten_phi を指定すると、計測値を AR(1) の残差 z̃_t = (z_t − c) − φ (z_{t−1} − c) + c に変えてから監視する
  （自己相関のある工程向けの特殊原因管理図。監視手法は同じ変換をした学習データで学習しておく）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from joblib import Parallel, delayed

from ..calibration import RecordTracker
from ..config import make_rng
from ..evaluation import arl_with_ci
from ..monitoring import SmoothedMaps, TemporalDetector
from ..simulation import MeasurementSystem
from ..temporal_process import CoefficientStream, temporal_profile


@dataclass
class TemporalSetup:
    system: MeasurementSystem
    detectors: list[TemporalDetector]
    center: np.ndarray
    prewhiten_phi: float | None = None
    lambdas: tuple = field(init=False)

    def __post_init__(self) -> None:
        self.lambdas = tuple(sorted({d.lam for d in self.detectors if d.lam is not None}))

    @property
    def names(self) -> list[str]:
        return [d.name for d in self.detectors]


def prewhiten_sequence(values: np.ndarray, center: np.ndarray, phi: float) -> np.ndarray:
    """学習データ（時系列順、W × 2N）を AR(1) 残差に変える。"""
    output = values.copy()
    output[1:] = center + (values[1:] - center) - phi * (values[:-1] - center)
    return output


def estimate_ar1(values: np.ndarray, center: np.ndarray) -> float:
    """時系列順の学習データから、全成分をまとめた AR(1) 係数を最小二乗で求める。"""
    deviation = values - center
    return float(np.sum(deviation[1:] * deviation[:-1]) / np.sum(deviation[:-1] ** 2))


def iterate(setup: TemporalSetup, rng: np.random.Generator, n_series: int, length: int, anomaly=None):
    """正常系列（＋異常）を 1 時点ずつ進め、(時点, 全検出器の統計量 n × D) を返す。anomaly(t) は 2N の変位。"""
    stream = CoefficientStream(setup.system.process, rng, n_series)
    maps = SmoothedMaps(setup.lambdas, setup.center, n_series)
    states = {d.name: d.init_state(n_series) for d in setup.detectors}
    previous = None
    for t in range(1, length + 1):
        values = setup.system.measure(stream.next(), rng)
        if anomaly is not None:
            shift = anomaly(t)
            if shift is not None:
                values = values + shift
        monitored = values
        if setup.prewhiten_phi is not None:
            # 最初の Wafer は前の Wafer がなく残差を作れないので、平均の地図（情報なし）として扱う
            # （生の計測値を入れると残差のモデルから見て極端な値になり、管理限界の校正が崩れる）
            if previous is None:
                monitored = np.broadcast_to(setup.center, values.shape).copy()
            else:
                monitored = setup.center + (values - setup.center) - setup.prewhiten_phi * (previous - setup.center)
            previous = values
        maps, step = maps.step(monitored)
        statistics = np.empty((n_series, len(setup.detectors)))
        for j, detector in enumerate(setup.detectors):
            states[detector.name], statistics[:, j] = detector.update(states[detector.name], step)
        yield t, statistics


def _tracker_block(setup: TemporalSetup, seed: int, key: tuple, block: int, n_runs: int, length: int) -> list[RecordTracker]:
    rng = make_rng(seed, *key, block)
    trackers = [RecordTracker(n_runs) for _ in setup.detectors]
    for t, statistics in iterate(setup, rng, n_runs, length):
        for j, tracker in enumerate(trackers):
            tracker.update(t, statistics[:, j])
    return trackers


def _merge_trackers(blocks: list[list[RecordTracker]]) -> list[RecordTracker]:
    merged = []
    for j in range(len(blocks[0])):
        parts = [block[j] for block in blocks]
        tracker = RecordTracker(sum(p.n_runs for p in parts))
        offset = 0
        for part in parts:
            run, time, value = part._arrays()
            tracker._run.append(run + offset)
            tracker._time.append(time)
            tracker._value.append(value)
            offset += part.n_runs
        tracker.length = max(p.length for p in parts)
        merged.append(tracker)
    return merged


def collect_trackers(setup, seed, key, n_runs, length, block_size=None, workers=1) -> list[RecordTracker]:
    if block_size is None:
        block_size = max(50, int(np.ceil(n_runs / max(workers, 1))))  # 並列の数に合わせて分ける
    sizes = [min(block_size, n_runs - s) for s in range(0, n_runs, block_size)]
    blocks = Parallel(n_jobs=workers)(delayed(_tracker_block)(setup, seed, key, b, size, length) for b, size in enumerate(sizes))
    return _merge_trackers(blocks)


def calibrate_thresholds(setup, seed, key, n_runs, length, target_arl, block_size=None, workers=1) -> tuple[dict, dict]:
    """正常系列で ARL₀ = 目標値 となる管理限界を検出器ごとに決める。"""
    trackers = collect_trackers(setup, seed, (*key, "arl_calibration"), n_runs, length, block_size, workers)
    thresholds, achieved = {}, {}
    for detector, tracker in zip(setup.detectors, trackers):
        thresholds[detector.name] = tracker.calibrate(target_arl)
        achieved[detector.name] = tracker.average_run_length(thresholds[detector.name])
    return thresholds, achieved


def validate_thresholds(setup, thresholds, seed, key, n_runs, length, block_size=None, workers=1) -> list[dict]:
    """独立な正常系列で、校正した管理限界の ARL₀ を確かめる（打ち切りの本数も返す）。"""
    trackers = collect_trackers(setup, seed, (*key, "arl_validation"), n_runs, length, block_size, workers)
    rows = []
    for detector, tracker in zip(setup.detectors, trackers):
        lengths = tracker.run_lengths(thresholds[detector.name])
        row = arl_with_ci(lengths)
        row.update({"detector": detector.name, "threshold": thresholds[detector.name], "censored_runs": int(np.sum(lengths > length)), "run_length": length})
        rows.append(row)
    return rows


@dataclass(frozen=True)
class Condition:
    pattern: str
    component: str
    amplitude: float


NULL_PATTERN = "no_change"


def null_condition() -> Condition:
    """変化を入れない基準の条件（変化点の後の誤報だけで「検出」になる割合を見る）。"""
    return Condition(NULL_PATTERN, "none", 0.0)


def _evaluate_condition(setup, thresholds, condition: Condition, unit_field, profile_params, seed, key, n_series, length, onset, block_size, record_example):
    if condition.amplitude == 0 or unit_field is None:
        anomaly = None
    else:
        profile = temporal_profile(condition.pattern, length, onset, profile_params)
        shift = condition.amplitude * unit_field

        def anomaly(t):
            g = profile[t - 1]
            return None if g == 0 else g * shift

    limits = np.array([thresholds[name] for name in setup.names])
    delays, before, example = [], [], None
    for block, start in enumerate(range(0, n_series, block_size)):
        size = min(block_size, n_series - start)
        rng = make_rng(seed, *key, "evaluation", block)  # 条件によらず同じ正常系列
        first = np.full((size, len(limits)), np.inf)
        pre = np.zeros((size, len(limits)), dtype=int)
        trace = []
        for t, statistics in iterate(setup, rng, size, length, anomaly):
            alarm = statistics > limits
            if t < onset:
                pre += alarm
            else:
                newly = alarm & np.isinf(first)
                first[newly] = t - onset + 1
            if record_example and block == 0:
                trace.append(statistics[0])
        delays.append(first)
        before.append(pre)
        if record_example and block == 0:
            example = np.array(trace)
    return condition, np.concatenate(delays), np.concatenate(before), example


def evaluate_conditions(
    setup, thresholds, conditions, unit_fields: dict, profile_params, seed, key, n_series, length, onset, block_size=1000, workers=1, example_condition=None
):
    """全条件の遅延（n_series × D）と変化点前の警報回数（警報が出た Wafer の数）を返す。unit_fields は成分名 → 2N の 1σ の変位。"""
    results = Parallel(n_jobs=workers)(
        delayed(_evaluate_condition)(
            setup, thresholds, c, unit_fields.get(c.component), profile_params, seed, key, n_series, length, onset, block_size, c == example_condition
        )
        for c in conditions
    )
    output = {}
    example = None
    for condition, delays, before, trace in results:
        output[condition] = (delays, before)
        if trace is not None:
            example = trace
    return output, example
