"""管理限界の校正（正常データから経験的に決める）。

- 1 Wafer の異常検知：正常（校正用）データのスコアの上側 α 分位点を管理限界にする（スコア > 限界 で警報）。
  "higher" の分位点を使うので、校正データ上の誤報率は α 以下になる。
- 複数指標の OR 判定：各指標を校正データの経験分布関数 F_j で [0, 1] に変換し、max_j F_j(s_j) を
  統合スコアとして同じように校正する（統合後の誤報率が α になる）。
- 時系列の異常検知：正常時の平均連長 ARL₀ が目標値になる管理限界を、正常系列のシミュレーションで二分探索する。
  連長は「統計量 > 限界 となる最初の時点」。各系列の記録値（それまでの最大値を更新した時点と値）だけを
  保存すれば、どの限界に対しても連長を計算できる（RecordTracker）。
"""
from __future__ import annotations

import numpy as np


def empirical_threshold(calibration_scores: np.ndarray, alpha: float) -> float:
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha は 0 と 1 の間")
    scores = np.asarray(calibration_scores, dtype=float)
    if np.ceil(alpha * len(scores)) < 5:
        raise ValueError(f"校正データが少なすぎる（α={alpha} に対して {len(scores)} 件）")
    return float(np.quantile(scores, 1.0 - alpha, method="higher"))


def alarm(scores: np.ndarray, threshold: float) -> np.ndarray:
    return np.asarray(scores) > threshold


class OrCombination:
    """複数の指標の OR 判定（経験分布関数で変換した値の最大値）。"""

    def __init__(self, names: list[str]):
        self.names = list(names)

    def fit(self, calibration_matrix: np.ndarray) -> "OrCombination":
        self.sorted_ = [np.sort(calibration_matrix[:, j]) for j in range(calibration_matrix.shape[1])]
        return self

    def transform(self, score_matrix: np.ndarray) -> np.ndarray:
        columns = []
        for j, reference in enumerate(self.sorted_):
            columns.append(np.searchsorted(reference, score_matrix[:, j], side="right") / len(reference))
        return np.max(np.column_stack(columns), axis=1)


class RecordTracker:
    """正常系列ごとに「最大値を更新した時点と値」を記録し、任意の限界に対する連長を返す。"""

    def __init__(self, n_runs: int):
        self.n_runs = n_runs
        self.running_max = np.full(n_runs, -np.inf)
        self._run, self._time, self._value = [], [], []
        self.length = 0

    def update(self, time: int, statistic: np.ndarray) -> None:
        """time は 1 始まり。"""
        new_record = statistic > self.running_max
        if np.any(new_record):
            index = np.flatnonzero(new_record)
            self._run.append(index)
            self._time.append(np.full(len(index), time))
            self._value.append(statistic[index])
            self.running_max[index] = statistic[index]
        self.length = max(self.length, time)

    def _arrays(self):
        if not hasattr(self, "_cache") or self._cache[0] != len(self._run):
            run = np.concatenate(self._run) if self._run else np.empty(0, dtype=int)
            time = np.concatenate(self._time) if self._time else np.empty(0, dtype=int)
            value = np.concatenate(self._value) if self._value else np.empty(0)
            self._cache = (len(self._run), run, time, value)
        return self._cache[1:]

    def run_lengths(self, threshold: float) -> np.ndarray:
        """各系列の連長。警報が出なかった系列は length + 1（打ち切り）。"""
        run, time, value = self._arrays()
        lengths = np.full(self.n_runs, self.length + 1)
        exceed = value > threshold
        np.minimum.at(lengths, run[exceed], time[exceed])
        return lengths

    def average_run_length(self, threshold: float) -> float:
        return float(self.run_lengths(threshold).mean())

    def calibrate(self, target_arl: float, iterations: int = 80) -> float:
        """ARL₀ ≥ 目標値 となる最小の限界（二分探索）。系列の長さは目標の数倍以上にしておく。"""
        if self.length < 3 * target_arl:
            raise ValueError("ARL₀ の校正には目標値の3倍以上の長さの正常系列が必要")
        _, _, value = self._arrays()
        low, high = float(value.min()) - 1.0, float(value.max())
        if self.average_run_length(high) < target_arl:
            raise ValueError("正常系列が短すぎて目標の ARL₀ に届かない")
        for _ in range(iterations):
            middle = 0.5 * (low + high)
            if self.average_run_length(middle) >= target_arl:
                high = middle
            else:
                low = middle
        return high
