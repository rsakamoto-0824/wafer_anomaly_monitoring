"""実データの検証の全体の流れ（画面・テスト・自己診断のどれからも、この run_analysis を呼ぶ）。

1. 共通の計測点・欠けの補完・学習／校正／評価への分割（dataset.py）
2. 1 Wafer の手法（M1〜M6）を学習期間で学習し、校正期間のスコアの上側 α 分位点を管理限界にする
   （検証と同じく、正常データから経験的に決める。"higher" の分位点なので校正期間の警報率は α 以下）
3. 選んだ手法の OR 統合（経験分布関数で [0, 1] に変換した値の最大値。統合後の誤報率で校正）
4. ラベルの列があれば、既知の異常との照合（検出率・誤報率・ROC-AUC）
5. 経時変化の監視（EWMA・CUSUM。ARL₀ で校正。temporal.py）
6. 異常の注入試験（1 Wafer・経時変化。injection.py）
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..config import make_rng
from ..evaluation import auc_interval, roc_auc, wilson_interval
from .dataset import SEGMENT_CALIBRATION, SEGMENT_EVALUATION, SEGMENT_TRAIN, AnalysisDataset, build_dataset
from .errors import UserFacingError, check_cancel
from .injection import single_wafer_summary, single_wafer_test, temporal_summary, temporal_test
from .methods import OrRule, build_monitors, monitor_details, nan_m3s_by_axis, score_monitor
from .preprocess import PreparedData
from .settings import AppSettings, method_family, method_label, or_members_label, or_name, validate_settings
from .temporal import (
    ARL_LENGTH_FACTOR,
    ARL_LENGTH_MARGIN,
    build_detectors,
    calibrate_arl,
    calibration_scores_by_base,
    detector_label,
    fit_detectors,
    run_real_sequence,
)

OR_THRESHOLD = 0.0  # OR 統合のスコアは「自分の管理限界からの距離」の最大値。0 を超えたら警報
ARL_CONSERVATIVE_RATIO = 1.2  # ブートストラップの ARL₀ が目標のこの倍を超えたら「保守的」と記す
MIN_EXPECTED_FALSE_ALARMS = 5  # 校正期間で α に当たる件数がこれ未満だと管理限界が不安定（検証の calibration.py と同じ目安）
STAGES = (  # 進み具合の配分（全体を 1 として）
    ("dataset", 0.04),
    ("fit", 0.14),
    ("single", 0.04),
    ("temporal", 0.30),
    ("injection_single", 0.14),
    ("injection_temporal", 0.34),
)


@dataclass
class AnalysisResult:
    settings: AppSettings
    dataset: AnalysisDataset
    monitors: dict
    skipped_methods: list
    single_names: list  # 1 Wafer の手法（OR 統合があれば最後）
    scores: pd.DataFrame  # 使う計測（行番号順）× 手法
    thresholds: dict
    alarms: pd.DataFrame
    method_table: pd.DataFrame
    m3s_values: pd.DataFrame  # 計測できた値だけの M3S（X・Y、nm）
    or_model: tuple | None = None
    temporal_detectors: list = field(default_factory=list)
    temporal_thresholds: np.ndarray | None = None
    temporal_stats: pd.DataFrame | None = None
    temporal_alarms: pd.DataFrame | None = None
    temporal_table: pd.DataFrame | None = None
    label_table: pd.DataFrame | None = None
    injection_single: pd.DataFrame | None = None
    injection_single_summary: pd.DataFrame | None = None
    injection_single_skipped: list = field(default_factory=list)
    injection_temporal: pd.DataFrame | None = None
    injection_temporal_summary: pd.DataFrame | None = None
    warnings: list = field(default_factory=list)
    elapsed_seconds: dict = field(default_factory=dict)

    @property
    def alpha(self) -> float:
        return self.settings.methods.alpha_percent / 100.0

    def label_of(self, name: str) -> str:
        for detector in self.temporal_detectors:
            if detector.name == name:
                return detector_label(detector)
        return method_label(name)


class _Progress:
    """段階ごとの進み具合（0〜1）を全体の進み具合に直して画面へ渡す。"""

    def __init__(self, callback, settings: AppSettings):
        self.callback = callback
        active = {"dataset", "fit", "single"}
        if settings.temporal.enabled:
            active.add("temporal")
        if settings.injection.single_enabled:
            active.add("injection_single")
        if settings.injection.temporal_enabled and settings.temporal.enabled:
            active.add("injection_temporal")
        weights = {name: weight for name, weight in STAGES if name in active}
        total = sum(weights.values())
        start = 0.0
        self.ranges = {}
        for name, weight in STAGES:
            if name in weights:
                self.ranges[name] = (start, start + weights[name] / total)
                start += weights[name] / total

    def stage(self, name: str):
        low, high = self.ranges[name]

        def report(fraction: float, message: str) -> None:
            if self.callback is not None:
                self.callback(low + (high - low) * min(max(fraction, 0.0), 1.0), message)

        return report


def empirical_limit(scores: np.ndarray, alpha: float) -> float:
    """正常（校正）スコアの上側 α 分位点（"higher"：校正期間の警報率は α 以下）。"""
    return float(np.quantile(np.asarray(scores, dtype=float), 1.0 - alpha, method="higher"))


def run_analysis(prepared: PreparedData, settings: AppSettings, progress=None, cancel=None) -> AnalysisResult:
    problems = validate_settings(settings)
    if problems:
        raise UserFacingError(
            "設定に直すところがあります。",
            "\n".join(f"・{problem}" for problem in problems),
            "「2. 設定」で上の項目を直してから、もう一度「検証を実行」を押してください。",
        )
    steps = _Progress(progress, settings)
    elapsed = {}
    warnings = []
    alpha = settings.methods.alpha_percent / 100.0

    started = time.perf_counter()
    report = steps.stage("dataset")
    report(0.0, "共通の計測点を決めて、欠けた点を補っています")
    dataset = build_dataset(prepared, settings.split, settings.data.wafer_radius_mm)
    warnings += dataset.notes
    elapsed["dataset"] = time.perf_counter() - started
    check_cancel(cancel)

    started = time.perf_counter()
    report = steps.stage("fit")
    monitors, skipped = build_monitors(dataset.points, settings.methods)
    if not monitors:
        raise UserFacingError(
            "使える監視手法がありません。",
            "選んだ手法がすべて、この計測点の数では計算できませんでした：" + "、".join(f"{method_label(n)}（{r}）" for n, r in skipped),
            "多項式の次数を下げるか、M3S・PCA など点の数によらない手法を選んでください。",
        )
    for name, reason in skipped:
        warnings.append(f"{method_label(name)} は使いません：{reason}。")
    train, calibration = dataset.rows(SEGMENT_TRAIN), dataset.rows(SEGMENT_CALIBRATION)
    for number, (name, monitor) in enumerate(monitors.items()):
        check_cancel(cancel)
        report(number / len(monitors), f"正常のモデルを学習しています（{method_label(name)}）")
        monitor.fit(dataset.observed[train] if getattr(monitor, "uses_observed_only", False) else dataset.filled[train])
    elapsed["fit"] = time.perf_counter() - started

    started = time.perf_counter()
    report = steps.stage("single")
    report(0.0, "1 Wafer ごとのスコアと管理限界を計算しています")
    names = list(monitors)
    score_matrix = np.column_stack([score_monitor(monitors[name], dataset.filled, dataset.observed) for name in names])
    thresholds = {name: empirical_limit(score_matrix[calibration, j], alpha) for j, name in enumerate(names)}
    expected = alpha * len(calibration)
    if expected < MIN_EXPECTED_FALSE_ALARMS:
        recommended = int(np.ceil(MIN_EXPECTED_FALSE_ALARMS / alpha))
        warnings.append(
            f"校正期間の計測が {len(calibration)} 件で、誤報率 {settings.methods.alpha_percent:g}% に当たる件数が {expected:.1f} 件しかありません。"
            f"管理限界が不安定です（目安は {recommended:,} 件以上）。誤報率を大きくするか、正常期間を長くしてください。"
        )
    scores = pd.DataFrame(score_matrix, columns=names)
    or_model = None
    members = [member for member in settings.methods.or_members if member in monitors] if settings.methods.or_enabled else []
    if settings.methods.or_enabled and len(members) < len(settings.methods.or_members):
        warnings.append("OR 統合から、使えなかった手法を除きました：" + "、".join(set(settings.methods.or_members) - set(members)))
    if len(members) >= 2:
        label = or_name(members)
        index = [names.index(member) for member in members]
        rule = OrRule(members).fit(score_matrix[calibration][:, index], alpha)
        or_model = (label, rule, OR_THRESHOLD)
        scores[label] = rule.transform(score_matrix[:, index])
        thresholds[label] = OR_THRESHOLD
    single_names = list(scores.columns)
    alarms = pd.DataFrame({name: scores[name].to_numpy() > thresholds[name] for name in single_names})
    m3s_values = pd.DataFrame(nan_m3s_by_axis(dataset.observed), columns=["M3S_X_nm", "M3S_Y_nm"])
    method_table = _method_table(dataset, monitors, single_names, scores, thresholds, alarms)
    label_table = _label_table(dataset, single_names, scores, alarms) if settings.data.label_column else None
    elapsed["single"] = time.perf_counter() - started

    result = AnalysisResult(
        settings, dataset, monitors, skipped, single_names, scores, thresholds, alarms, method_table, m3s_values, or_model,
        label_table=label_table, warnings=warnings, elapsed_seconds=elapsed,
    )

    if settings.temporal.enabled:
        started = time.perf_counter()
        _temporal(result, steps.stage("temporal"), cancel)
        elapsed["temporal"] = time.perf_counter() - started
        if label_table is not None:
            result.label_table = pd.concat([label_table, _temporal_label_rows(result)], ignore_index=True)

    if settings.injection.single_enabled:
        started = time.perf_counter()
        table, skipped_patterns = single_wafer_test(
            dataset, monitors, thresholds, or_model, settings.injection, settings.seed, steps.stage("injection_single"), cancel
        )
        result.injection_single = table
        result.injection_single_summary = single_wafer_summary(table)
        result.injection_single_skipped = skipped_patterns
        for pattern, reason in skipped_patterns:
            warnings.append(f"注入試験の {pattern} は行いません：{reason}。")
        elapsed["injection_single"] = time.perf_counter() - started

    if settings.injection.temporal_enabled and settings.temporal.enabled and result.temporal_detectors:
        started = time.perf_counter()
        center = dataset.filled[train].mean(axis=0)
        table = temporal_test(
            dataset, result.temporal_detectors, result.temporal_thresholds, center, settings.injection, settings.temporal,
            settings.seed, steps.stage("injection_temporal"), cancel,
        )
        result.injection_temporal = table
        result.injection_temporal_summary = temporal_summary(table)
        elapsed["injection_temporal"] = time.perf_counter() - started
    if progress is not None:
        progress(1.0, "検証が終わりました")
    return result


def _segment_rates(dataset: AnalysisDataset, flags: np.ndarray, segment: str) -> tuple[int, int]:
    rows = dataset.rows(segment)
    return int(len(rows)), int(np.sum(flags[rows]))


def _method_table(dataset, monitors, names, scores, thresholds, alarms) -> pd.DataFrame:
    rows = []
    m3s = alarms["M3S_XY"].to_numpy() if "M3S_XY" in alarms else None
    evaluation = dataset.rows(SEGMENT_EVALUATION)
    for name in names:
        flags = alarms[name].to_numpy()
        n_train, k_train = _segment_rates(dataset, flags, SEGMENT_TRAIN)
        n_cal, k_cal = _segment_rates(dataset, flags, SEGMENT_CALIBRATION)
        n_eval, k_eval = _segment_rates(dataset, flags, SEGMENT_EVALUATION)
        only = int(np.sum(flags[evaluation] & ~m3s[evaluation])) if m3s is not None and name != "M3S_XY" else np.nan
        rows.append(
            {
                "method": name,
                "label": method_label(name),
                "family": method_family(name),
                "threshold": thresholds[name],
                "train_alarm_rate": k_train / n_train if n_train else np.nan,
                "calibration_n": n_cal,
                "calibration_alarms": k_cal,
                "calibration_alarm_rate": k_cal / n_cal if n_cal else np.nan,
                "evaluation_n": n_eval,
                "evaluation_alarms": k_eval,
                "evaluation_alarm_rate": k_eval / n_eval if n_eval else np.nan,
                "evaluation_alarms_without_m3s": only,
                "details": monitor_details(name, monitors[name]) if name in monitors else f"構成：{or_members_label(name)}",
            }
        )
    return pd.DataFrame(rows)


def _label_masks(dataset: AnalysisDataset) -> tuple[np.ndarray, np.ndarray]:
    used = dataset.used
    positive = used.loc[used["label"], "row"].to_numpy(dtype=int)
    negative = used.loc[(~used["label"]) & (used["segment"] == SEGMENT_EVALUATION), "row"].to_numpy(dtype=int)
    return positive, negative


def _label_table(dataset, names, scores, alarms) -> pd.DataFrame:
    """ラベルとの照合。陽性＝ラベルで異常の計測、陰性＝評価期間のラベルのない計測（気づいていない異常が混じりうる）。"""
    positive, negative = _label_masks(dataset)
    rows = []
    for name in names:
        rows.append(_label_row(name, method_label(name), "1 Wafer", scores[name].to_numpy(), alarms[name].to_numpy(), positive, negative))
    return pd.DataFrame(rows)


def _label_row(name, label, kind, score, flags, positive, negative) -> dict:
    positive = positive[np.isfinite(score[positive])] if len(positive) else positive
    negative = negative[np.isfinite(score[negative])] if len(negative) else negative
    row = {"method": name, "label": label, "kind": kind, "n_positive": len(positive), "n_negative": len(negative)}
    hits = int(flags[positive].sum()) if len(positive) else 0
    false = int(flags[negative].sum()) if len(negative) else 0
    row["detected"] = hits
    row["detection_rate"] = hits / len(positive) if len(positive) else np.nan
    low, high = wilson_interval(hits, len(positive)) if len(positive) else (np.nan, np.nan)
    row["detection_ci_low"], row["detection_ci_high"] = float(low), float(high)
    row["false_alarms"] = false
    row["false_alarm_rate"] = false / len(negative) if len(negative) else np.nan
    if len(positive) and len(negative):
        auc = roc_auc(score[negative], score[positive])
        row["roc_auc"] = auc
        row["auc_ci_low"], row["auc_ci_high"] = auc_interval(auc, len(positive), len(negative))
    else:
        row["roc_auc"] = row["auc_ci_low"] = row["auc_ci_high"] = np.nan
    return row


def _temporal(result: AnalysisResult, report, cancel) -> None:
    dataset, settings = result.dataset, result.settings
    detectors = build_detectors(result.monitors, settings.temporal)
    missing = [base for base in settings.temporal.bases if base not in result.monitors]
    if missing:
        result.warnings.append("経時変化の監視から、使えなかった手法を除きました：" + "、".join(method_label(m) for m in missing))
    if not detectors:
        return
    train, calibration = dataset.rows(SEGMENT_TRAIN), dataset.rows(SEGMENT_CALIBRATION)
    calibration_scores = calibration_scores_by_base(detectors, dataset.filled[calibration], dataset.observed[calibration])
    fit_detectors(detectors, dataset.filled[train], calibration_scores)
    center = dataset.filled[train].mean(axis=0)
    rng = make_rng(settings.seed, "temporal", "arl")
    thresholds, arl = calibrate_arl(
        detectors, center, dataset.filled[calibration], dataset.observed[calibration], settings.temporal, rng, report, cancel
    )
    report(0.95, "経時変化の監視を実データの系列に当てています")
    # 実データの系列：校正期間の最初の計測から後ろ（学習期間の計測は正常の基準を作るのに使ったので含めない）
    start = int(calibration.min())
    rows = np.arange(start, len(dataset.filled))
    statistics = run_real_sequence(detectors, thresholds, center, dataset.filled[rows], dataset.observed[rows], cancel)
    names = [detector.name for detector in detectors]
    full = np.full((len(dataset.filled), len(detectors)), np.nan)
    full[rows] = statistics
    stats = pd.DataFrame(full, columns=names)
    alarms = pd.DataFrame({name: stats[name].to_numpy() > h for name, h in zip(names, thresholds)})
    result.temporal_detectors = detectors
    result.temporal_thresholds = thresholds
    result.temporal_stats = stats
    result.temporal_alarms = alarms
    used = dataset.used.reset_index(drop=True)
    target = settings.temporal.target_arl0
    censored_length = ARL_LENGTH_FACTOR * target + ARL_LENGTH_MARGIN
    notes = [_arl_note(value, target, censored_length) for value in arl]
    n_censored = sum(1 for value in arl if value > censored_length)
    if n_censored:
        result.warnings.append(
            f"経時変化の監視で、管理限界を目標の ARL₀（{target:g} 枚）にそろえられない検出器が {n_censored} 個あります（主に Shewhart）。"
            f"校正期間の計測が {len(calibration)} 件で、目標に比べて少ないためです。これらは校正期間の最大値を限界にしたので、"
            "ほかの検出器より警報が出にくい側に偏ります。正常期間を長くするか、ARL₀ の目標を小さくしてください"
            "（目安：校正期間の計測が ARL₀ の 2 倍以上）。"
        )
    table = []
    for j, detector in enumerate(detectors):
        flags = alarms[detector.name].to_numpy()
        n_cal, k_cal = _segment_rates(dataset, flags, SEGMENT_CALIBRATION)
        n_eval, k_eval = _segment_rates(dataset, flags, SEGMENT_EVALUATION)
        evaluation = dataset.rows(SEGMENT_EVALUATION)
        first = evaluation[flags[evaluation]]
        param = detector.smoothing if detector.scheme == "ewma" else (detector.k if detector.scheme == "cusum" else np.nan)
        table.append(
            {
                "detector": detector.name,
                "label": detector_label(detector),
                "base": detector.monitor.name,
                "scheme": detector.scheme + ("-scalar" if getattr(detector, "mode", "") == "scalar" and detector.scheme == "ewma" else ""),
                "param": param,
                "threshold": thresholds[j],
                "bootstrap_arl0": arl[j],
                "limit_note": notes[j],
                "calibration_n": n_cal,
                "calibration_alarms": k_cal,
                "expected_calibration_alarms": n_cal / settings.temporal.target_arl0,
                "evaluation_n": n_eval,
                "evaluation_alarms": k_eval,
                "first_evaluation_alarm_order": int(used.loc[first[0], "order"]) if len(first) else np.nan,
                "first_evaluation_alarm_wafer": used.loc[first[0], "Wafer"] if len(first) else "",
            }
        )
    result.temporal_table = pd.DataFrame(table)
    report(1.0, "経時変化の監視が終わりました")


def _arl_note(value: float, target: float, censored_length: float) -> str:
    if value > censored_length:
        return "校正期間の最大値（目標の ARL₀ にそろえられない。警報が出にくい側）"
    if value > ARL_CONSERVATIVE_RATIO * target:
        return f"目標より保守的（ARL₀ の推定 {value:.0f} 枚）"
    return ""


def _temporal_label_rows(result: AnalysisResult) -> pd.DataFrame:
    positive, negative = _label_masks(result.dataset)
    rows = []
    for detector in result.temporal_detectors:
        stats = result.temporal_stats[detector.name].to_numpy()
        flags = result.temporal_alarms[detector.name].to_numpy()
        rows.append(_label_row(detector.name, detector_label(detector), "経時変化", stats, flags, positive, negative))
    return pd.DataFrame(rows)
