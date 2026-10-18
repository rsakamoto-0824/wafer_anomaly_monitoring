"""結果の要点を、短い日本語の文にする（画面の「概要」と保存する Excel の「概要」で使う）。

数値は結果の表からそのまま取り出し、解釈を足さない（どの手法が良いかは、同じ誤報率で比べた数値だけで述べる）。
"""
from __future__ import annotations

import numpy as np

from .dataset import SEGMENT_CALIBRATION, SEGMENT_EVALUATION, SEGMENT_EXCLUDED, SEGMENT_LABEL_EXCLUDED, SEGMENT_TRAIN
from .settings import method_label

MAX_LISTED_METHODS = 8


def key_findings(result) -> list[str]:
    lines = [_data_line(result), _single_line(result)]
    lines += _temporal_lines(result)
    lines += _label_lines(result)
    lines += _injection_lines(result)
    return [line for line in lines if line]


def _data_line(result) -> str:
    counts = result.dataset.measurements["segment"].value_counts()
    parts = [f"{name} {int(counts.get(name, 0)):,}" for name in (SEGMENT_TRAIN, SEGMENT_CALIBRATION, SEGMENT_EVALUATION)]
    extra = []
    if counts.get(SEGMENT_LABEL_EXCLUDED, 0):
        extra.append(f"正常期間でラベルが異常のため学習・校正から除いた {int(counts[SEGMENT_LABEL_EXCLUDED]):,} 件")
    if counts.get(SEGMENT_EXCLUDED, 0):
        extra.append(f"欠けが多く除いた {int(counts[SEGMENT_EXCLUDED]):,} 件")
    text = f"計測 {len(result.dataset.measurements):,} 件（{'・'.join(parts)} 件）、共通の計測点 {result.dataset.n_points:,} 点。"
    return text + ("（" + "、".join(extra) + "）" if extra else "")


def _single_line(result) -> str:
    table = result.method_table
    n_eval = int(table["evaluation_n"].iloc[0]) if len(table) else 0
    if n_eval == 0:
        return f"評価期間の計測がないため、1 Wafer の判定は校正期間までです（誤報率 {result.settings.methods.alpha_percent:g}%）。"
    listed = table.sort_values("evaluation_alarms", ascending=False).head(MAX_LISTED_METHODS)
    counts = "、".join(f"{row.label} {int(row.evaluation_alarms)} 件" for row in listed.itertuples())
    text = f"1 Wafer の判定（誤報率 {result.settings.methods.alpha_percent:g}%）：評価期間 {n_eval:,} 件で警報が出た数は {counts}。"
    if "M3S_XY" in result.alarms:
        evaluation = result.dataset.rows(SEGMENT_EVALUATION)
        others = [name for name in result.single_names if name != "M3S_XY"]
        if others:
            any_other = result.alarms[others].to_numpy()[evaluation].any(axis=1)
            m3s = result.alarms["M3S_XY"].to_numpy()[evaluation]
            text += f"M3S では警報が出ず、ほかの手法のどれかで警報が出た計測は {int(np.sum(any_other & ~m3s)):,} 件（判定一覧で確認できます）。"
    return text


def _temporal_lines(result) -> list[str]:
    table = result.temporal_table
    if table is None or table.empty:
        return []
    target = result.settings.temporal.target_arl0
    first = table.dropna(subset=["first_evaluation_alarm_order"])
    if first.empty:
        return [f"経時変化の監視（ARL₀ {target:g} 枚）：評価期間で警報を出した検出器はありません。"]
    earliest = first.sort_values("first_evaluation_alarm_order").iloc[0]
    count = int((table["evaluation_alarms"] > 0).sum())
    return [
        f"経時変化の監視（ARL₀ {target:g} 枚）：評価期間で警報を出した検出器は {count} / {len(table)} 個。"
        f"最初に警報を出したのは {earliest['label']}（{int(earliest['first_evaluation_alarm_order'])} 番目の計測・{earliest['first_evaluation_alarm_wafer']}）。"
    ]


def _label_lines(result) -> list[str]:
    table = result.label_table
    if table is None or table.empty:
        return []
    n_positive = int(table["n_positive"].iloc[0])
    if n_positive == 0:
        return ["ラベルで「異常」とされた計測が、解析に使った計測の中にありません（照合はできません）。"]
    single = table[table["kind"] == "1 Wafer"].sort_values(["detected", "roc_auc"], ascending=False)
    best = single.iloc[0]
    line = f"既知の異常 {n_positive} 件との照合（1 Wafer）：検出が最も多いのは {best['label']}（{int(best['detected'])} / {n_positive} 件）。"
    m3s = single[single["method"] == "M3S_XY"]
    if not m3s.empty:
        line += f"M3S は {int(m3s.iloc[0]['detected'])} / {n_positive} 件。"
    return [line]


def _injection_lines(result) -> list[str]:
    lines = []
    summary = result.injection_single_summary
    if summary is not None and not summary.empty:
        best = summary.iloc[0]
        line = (
            f"異常の注入試験（1 Wafer、誤報率 {result.settings.methods.alpha_percent:g}%）：平均の検出率が最も高いのは "
            f"{method_label(best['method'])}（{best['mean_detection']:.0%}）。"
        )
        m3s = summary[summary["method"] == "M3S_XY"]
        if not m3s.empty:
            line += f"M3S は {m3s.iloc[0]['mean_detection']:.0%}。"
        if "mean_detection_m3s_blind" in summary and summary["mean_detection_m3s_blind"].notna().any():
            blind = summary.sort_values("mean_detection_m3s_blind", ascending=False).iloc[0]
            line += (
                f"M3S の検出率が 10% 未満の {int(blind['n_m3s_blind_conditions'])} 条件では、"
                f"{method_label(blind['method'])} が {blind['mean_detection_m3s_blind']:.0%}。"
            )
        lines.append(line)
    summary = result.injection_temporal_summary
    if summary is not None and not summary.empty:
        best = summary.iloc[0]
        line = f"異常の注入試験（経時変化）：気づくまでの平均の枚数（RMST）が最も短いのは {best['detector_label']}（{best['mean_rmst_delay']:.1f} 枚）。"
        m3s = summary[summary["detector"].str.startswith("M3S_XY|")]
        if not m3s.empty:
            line += f"M3S の中で最も短いのは {m3s.iloc[0]['detector_label']}（{m3s.iloc[0]['mean_rmst_delay']:.1f} 枚）。"
        lines.append(line)
    return lines
