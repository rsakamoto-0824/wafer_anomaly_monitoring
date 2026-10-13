"""性能指標と 95% 信頼区間。

1 Wafer の異常検知
- 検出率（Recall）・誤報率（FPR）：Wilson の信頼区間。
- ROC-AUC：Mann–Whitney の U（同順位は 0.5）。信頼区間は Hanley & McNeil (1982) の標準誤差。
- PR-AUC：平均適合率（Average Precision）。陽性（異常）と陰性（正常）の件数比は実際に使った件数のまま。
  信頼区間は陽性側の Poisson ブートストラップ（陰性は件数が多いので固定）。
- 検出可能な最小異常振幅（MDA）：検出率が 50%・90% に達する振幅（対数軸で線形補間。届かなければ NaN）。

時系列の経時変化検知（変化点 onset、変化後の観測窓 window 枚）
- 検出遅延 D = 警報時点 − onset + 1（変化後 1 枚目で警報なら 1）。窓の中で警報がない系列は打ち切り（D > window）。
- 検出率（窓の中で検出した割合）、制限付き平均遅延 RMST = E[min(D, window)]（未検出は window として数える。
  打ち切りがすべて同じ時点なので Kaplan–Meier の生存曲線の面積と一致）、遅延の中央値（Kaplan–Meier。
  検出率が 50% 未満なら求まらない）、検出した系列だけの平均遅延（参考。これだけで優劣を判断しない）。
- ARL₀：正常系列の平均連長。信頼区間は正規近似。
"""
from __future__ import annotations

import numpy as np

Z95 = 1.959963984540054


def wilson_interval(successes, trials, z: float = Z95) -> tuple[np.ndarray, np.ndarray]:
    successes = np.asarray(successes, dtype=float)
    trials = np.asarray(trials, dtype=float)
    p = np.divide(successes, trials, out=np.zeros_like(successes), where=trials > 0)
    denom = 1.0 + z * z / trials
    center = (p + z * z / (2 * trials)) / denom
    half = z * np.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denom
    return np.clip(center - half, 0, 1), np.clip(center + half, 0, 1)


def rate_with_ci(flags: np.ndarray) -> dict[str, float]:
    flags = np.asarray(flags, dtype=bool)
    k, n = int(flags.sum()), len(flags)
    low, high = wilson_interval(k, n)
    return {"rate": k / n if n else np.nan, "ci_low": float(low), "ci_high": float(high), "n": n, "k": k}


def roc_auc(negative: np.ndarray, positive: np.ndarray) -> float:
    """P(陽性のスコア > 陰性のスコア) + 0.5 P(同じ)。"""
    negative = np.sort(np.asarray(negative, dtype=float))
    positive = np.asarray(positive, dtype=float)
    below = np.searchsorted(negative, positive, side="left")
    equal = np.searchsorted(negative, positive, side="right") - below
    return float(np.mean((below + 0.5 * equal) / len(negative)))


def auc_interval(auc: float, n_positive: int, n_negative: int) -> tuple[float, float]:
    """Hanley & McNeil (1982) の標準誤差による正規近似。"""
    q1 = auc / (2 - auc)
    q2 = 2 * auc * auc / (1 + auc)
    variance = (auc * (1 - auc) + (n_positive - 1) * (q1 - auc * auc) + (n_negative - 1) * (q2 - auc * auc)) / (
        n_positive * n_negative
    )
    se = np.sqrt(max(variance, 0.0))
    return max(0.0, auc - Z95 * se), min(1.0, auc + Z95 * se)


def _precision_at_positives(negative_desc: np.ndarray, positive: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """各陽性のスコアを限界にしたときの適合率（陽性の重み付き）。negative_desc は降順。"""
    order = np.argsort(-positive, kind="stable")
    sorted_pos = positive[order]
    cumulative = np.cumsum(weights[order])
    # 同じスコアの陽性はまとめて数える（そのスコア以上の陽性の重みの合計）
    last_of_tie = np.searchsorted(-sorted_pos, -sorted_pos, side="right") - 1
    true_positive = cumulative[last_of_tie]
    false_positive = np.searchsorted(-negative_desc, -sorted_pos, side="right")
    total = true_positive + false_positive
    precision = np.empty_like(positive, dtype=float)
    # 分母が0になるのは重み0の陽性だけ（平均には効かない）
    precision[order] = np.divide(true_positive, total, out=np.zeros_like(true_positive, dtype=float), where=total > 0)
    return precision


def average_precision(negative: np.ndarray, positive: np.ndarray) -> float:
    negative_desc = np.sort(np.asarray(negative, dtype=float))[::-1]
    positive = np.asarray(positive, dtype=float)
    return float(np.mean(_precision_at_positives(negative_desc, positive, np.ones(len(positive)))))


def average_precision_interval(
    negative: np.ndarray, positive: np.ndarray, rng: np.random.Generator, n_boot: int = 200
) -> tuple[float, float]:
    negative_desc = np.sort(np.asarray(negative, dtype=float))[::-1]
    positive = np.asarray(positive, dtype=float)
    values = []
    for _ in range(n_boot):
        weights = rng.poisson(1.0, len(positive)).astype(float)
        if weights.sum() == 0:
            continue
        precision = _precision_at_positives(negative_desc, positive, weights)
        values.append(np.sum(weights * precision) / weights.sum())
    return float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))


def minimum_detectable_amplitude(amplitudes, rates, level: float) -> float:
    """検出率が level に達する最小の振幅（log 振幅で線形補間）。最小振幅で既に達していればその値。"""
    amplitudes = np.asarray(amplitudes, dtype=float)
    rates = np.asarray(rates, dtype=float)
    order = np.argsort(amplitudes)
    amplitudes, rates = amplitudes[order], rates[order]
    reached = np.flatnonzero(rates >= level)
    if len(reached) == 0:
        return float("nan")
    i = reached[0]
    if i == 0:
        return float(amplitudes[0])
    a0, a1 = np.log(amplitudes[i - 1]), np.log(amplitudes[i])
    r0, r1 = rates[i - 1], rates[i]
    return float(np.exp(a0 + (level - r0) * (a1 - a0) / (r1 - r0)))


# ---------------------------------------------------------------------- 時系列
def delay_summary(delays: np.ndarray, window: int, rng: np.random.Generator | None = None, n_boot: int = 300) -> dict:
    """遅延（未検出は np.inf）から検出率・制限付き平均遅延・中央値などを求める。"""
    delays = np.asarray(delays, dtype=float)
    detected = delays <= window
    capped = np.minimum(delays, window)
    summary = rate_with_ci(detected)
    summary = {"detection_rate": summary["rate"], "detection_ci_low": summary["ci_low"], "detection_ci_high": summary["ci_high"], "n_series": summary["n"]}
    summary["rmst_delay"] = float(capped.mean())
    summary["median_delay"] = _km_median(delays, window)
    summary["mean_delay_detected"] = float(delays[detected].mean()) if detected.any() else float("nan")
    if rng is not None:
        index = rng.integers(0, len(delays), (n_boot, len(delays)))
        boot_rmst = capped[index].mean(axis=1)
        summary["rmst_ci_low"], summary["rmst_ci_high"] = (float(v) for v in np.quantile(boot_rmst, [0.025, 0.975]))
        boot_median = np.array([_km_median(delays[row], window) for row in index])
        finite = boot_median[np.isfinite(boot_median)]
        if len(finite) >= 0.9 * n_boot:
            summary["median_ci_low"], summary["median_ci_high"] = (float(v) for v in np.quantile(finite, [0.025, 0.975]))
        else:
            summary["median_ci_low"] = summary["median_ci_high"] = float("nan")
    return summary


def _km_median(delays: np.ndarray, window: int) -> float:
    """打ち切りが窓の終わりだけなので、Kaplan–Meier の中央値＝累積検出率が 50% に達した最初の遅延。"""
    detected = np.sort(delays[delays <= window])
    needed = int(np.ceil(0.5 * len(delays)))
    return float(detected[needed - 1]) if len(detected) >= needed else float("nan")


def arl_with_ci(run_lengths: np.ndarray) -> dict[str, float]:
    run_lengths = np.asarray(run_lengths, dtype=float)
    mean = run_lengths.mean()
    se = run_lengths.std(ddof=1) / np.sqrt(len(run_lengths))
    return {"arl": float(mean), "arl_ci_low": float(mean - Z95 * se), "arl_ci_high": float(mean + Z95 * se), "n_runs": len(run_lengths)}


def conditional_delays(delays: np.ndarray, pre_change_alarms: np.ndarray) -> tuple[np.ndarray, float]:
    """条件付き期待遅延の対象：変化点より前に警報が出なかった系列の遅延と、前に警報が出た系列の割合。"""
    clean = np.asarray(pre_change_alarms) == 0
    return np.asarray(delays)[clean], float(np.mean(~clean))


def first_alarm_delays(statistics: np.ndarray, threshold: float, onset: int) -> tuple[np.ndarray, np.ndarray]:
    """統計量（n × T、時点 1..T）から、変化点以降の最初の警報の遅延と、変化点前の警報回数を返す。"""
    alarms = statistics > threshold
    before = alarms[:, : onset - 1].sum(axis=1)
    after = alarms[:, onset - 1 :]
    has_alarm = after.any(axis=1)
    delays = np.where(has_alarm, after.argmax(axis=1) + 1, np.inf)
    return delays, before
