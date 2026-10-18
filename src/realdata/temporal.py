"""経時変化の監視（Shewhart・EWMA・CUSUM）を実データで使うための部品。

管理限界は検証と同じく「正常時の平均連長 ARL₀ が目標値（既定 370 枚）」になるように決める。
実データの正常期間は短いので、校正期間の Wafer を「ブロック単位で並べ替えた長い正常系列」を作って使う
（移動ブロック・ブートストラップ。ブロックの長さは既定 25 枚＝1 Lot で、Lot の中の似かたを残す）。
ブロックより長い周期のゆっくりした変動は再現されないので、実際の誤報はこれより多くなることがある
（校正期間での実際の警報数も結果に出す）。

検出器の中身は検証のコード（src/monitoring の EWMA・CUSUM・Shewhart）をそのまま使う。
- 正常時の基準（S₀、係数の平均・共分散）は学習期間で決める。
- スカラーの EWMA・CUSUM の標準化（平均・標準偏差）は、校正期間のスコアで決める
  （学習に使った Wafer のスコアは小さめに出るので、学習期間で標準化すると CUSUM の参照値 k の意味がずれるため）。
"""
from __future__ import annotations

import numpy as np

from ..calibration import RecordTracker
from ..experiments.common import build_temporal_detectors
from ..monitoring import Monitor, SmoothedMaps, StepInput, TemporalDetector
from .errors import check_cancel
from .methods import score_monitor
from .settings import TemporalOptions, method_label, temporal_parameter_sets

ARL_LENGTH_FACTOR = 3  # RecordTracker の校正には目標の3倍以上の長さが必要
ARL_LENGTH_MARGIN = 10


class RealStepInput(StepInput):
    """ある時点の計測値（補ったもの）に、欠測を NaN のまま残した値を添える（M3S は計測できた値だけで計算するため）。"""

    def __init__(self, values: np.ndarray, observed: np.ndarray, smoothed: dict | None = None):
        super().__init__(values, smoothed)
        self.observed = observed

    def score(self, monitor: Monitor, lam: float | None = None) -> np.ndarray:
        if lam is None and getattr(monitor, "uses_observed_only", False):
            key = ("score_observed", id(monitor))
            if key not in self._cache:
                self._cache[key] = monitor.score(self.observed)
            return self._cache[key]
        return super().score(monitor, lam)


def build_detectors(monitors: dict[str, Monitor], options: TemporalOptions) -> list[TemporalDetector]:
    detectors: list[TemporalDetector] = []
    for base in options.bases:
        if base not in monitors:
            continue
        lambdas, ks = temporal_parameter_sets(options, base)
        detectors += build_temporal_detectors({base: monitors[base]}, [base], lambdas, ks, shewhart=options.include_shewhart)
    return detectors


def detector_label(detector: TemporalDetector) -> str:
    base = method_label(detector.monitor.name)
    if detector.scheme == "shewhart":
        return f"{base}｜Shewhart（1枚ごと）"
    if detector.scheme == "ewma":
        kind = "EWMA（スコア）" if getattr(detector, "mode", "") == "scalar" else "EWMA（計測値）"
        return f"{base}｜{kind} λ={detector.smoothing:g}"
    return f"{base}｜CUSUM k={detector.k:g}"


def fit_detectors(detectors, train_filled: np.ndarray, calibration_scores: dict[str, np.ndarray]) -> None:
    """検出器の基準を決める（スカラーの標準化は校正期間のスコアで）。"""
    for detector in detectors:
        if getattr(detector, "mode", None) == "scalar":
            scores = calibration_scores[detector.monitor.name]
            detector.mean_ = float(np.mean(scores))
            detector.sd_ = float(np.std(scores, ddof=1)) or 1.0
        else:
            detector.fit(train_filled)


def run_detectors(detectors, center: np.ndarray, n_series: int, length: int, provider, on_step, cancel=None) -> None:
    """provider(t) → (補った値, 欠測を残した値)（各 n_series × 2N）を時間の順に流し、on_step(t, 統計量) を呼ぶ。

    警報が出ても統計量はリセットしない（検証と同じ）。統計量は n_series × 検出器数。
    """
    lambdas = sorted({detector.lam for detector in detectors if detector.lam is not None})
    maps = SmoothedMaps(lambdas, center, n_series)
    states = [detector.init_state(n_series) for detector in detectors]
    statistics = np.empty((n_series, len(detectors)))
    for t in range(length):
        if t % 20 == 0:
            check_cancel(cancel)
        values, observed = provider(t)
        maps = maps.advance(values)
        step = RealStepInput(values, observed, maps.state)
        for j, detector in enumerate(detectors):
            states[j], statistics[:, j] = detector.update(states[j], step)
        on_step(t, statistics)


def block_bootstrap_indices(n_pool: int, n_series: int, length: int, block: int, rng: np.random.Generator) -> np.ndarray:
    """移動ブロック・ブートストラップの番号（n_series × length）。連続した block 枚を無作為な位置から切り出してつなぐ。"""
    block = max(1, min(int(block), n_pool))
    n_blocks = int(np.ceil(length / block))
    starts = rng.integers(0, n_pool - block + 1, (n_series, n_blocks))
    index = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n_series, -1)
    return index[:, :length]


def calibrate_arl(detectors, center, calibration_filled, calibration_observed, options: TemporalOptions, rng, progress=None, cancel=None):
    """校正期間の Wafer をブロック単位で並べた正常系列で、ARL₀ が目標になる管理限界を決める。"""
    length = int(ARL_LENGTH_FACTOR * options.target_arl0) + ARL_LENGTH_MARGIN
    n_series = int(options.n_bootstrap_series)
    index = block_bootstrap_indices(len(calibration_filled), n_series, length, options.block_length, rng)
    trackers = [RecordTracker(n_series) for _ in detectors]

    def provider(t):
        return calibration_filled[index[:, t]], calibration_observed[index[:, t]]

    def on_step(t, statistics):
        for j, tracker in enumerate(trackers):
            tracker.update(t + 1, statistics[:, j])
        if progress is not None and t % 50 == 0:
            progress(t / length, f"経時変化の管理限界を計算中（{t:,} / {length:,} 枚）")

    run_detectors(detectors, center, n_series, length, provider, on_step, cancel)
    thresholds = np.array([tracker.calibrate(options.target_arl0) for tracker in trackers])
    arl = np.array([tracker.average_run_length(h) for tracker, h in zip(trackers, thresholds)])
    return thresholds, arl


def run_real_sequence(detectors, thresholds, center, filled: np.ndarray, observed: np.ndarray, cancel=None) -> np.ndarray:
    """実データの1本の系列（時間の順）での統計量（枚数 × 検出器数）。

    警報が出たら、その検出器の統計量を最初（正常時の基準）からやり直す。ARL₀ は「最初から数えて最初の警報まで」の
    平均なので、やり直すと正常時の警報の数がおよそ 枚数 / ARL₀ になる（やり直さないと、CUSUM などは一度限界を
    超えると下がりにくく、警報が続いて見える）。やり直しは検出器ごとなので、計測値の EWMA も検出器ごとに持つ。
    """
    output = np.empty((len(filled), len(detectors)))
    for j, (detector, threshold) in enumerate(zip(detectors, thresholds)):
        check_cancel(cancel)
        lambdas = [detector.lam] if detector.lam is not None else []
        maps = SmoothedMaps(lambdas, center, 1)
        state = detector.init_state(1)
        for t in range(len(filled)):
            maps = maps.advance(filled[t : t + 1])
            step = RealStepInput(filled[t : t + 1], observed[t : t + 1], maps.state)
            state, statistic = detector.update(state, step)
            output[t, j] = statistic[0]
            if statistic[0] > threshold:
                maps = SmoothedMaps(lambdas, center, 1)
                state = detector.init_state(1)
    return output


def calibration_scores_by_base(detectors, filled: np.ndarray, observed: np.ndarray) -> dict[str, np.ndarray]:
    scores = {}
    for detector in detectors:
        name = detector.monitor.name
        if name not in scores:
            scores[name] = score_monitor(detector.monitor, filled, observed)
    return scores
