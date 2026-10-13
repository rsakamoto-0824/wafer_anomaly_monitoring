"""技術レポート（Markdown）の作成。

レポートの文章は reports/technical_report_template.md に書き、数値と表は集計 CSV から埋め込む。
- {{v:キー}}   … VALUE_SPECS の値（CSV の行を条件で絞り、列を集計して書式化した文字列）
- {{t:表の名前}} … TABLE_BUILDERS の表（CSV から作る Markdown の表）
埋め込んだ値は results/metrics/report_values.csv に「どの CSV のどの行・列から作ったか」と一緒に保存し、
テスト（tests/test_15_report_consistency.py）で CSV と一致することを確かめる。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .anomaly_generator import SINGLE_WAFER_PATTERNS, TEMPORAL_COMPONENTS
from .config import PROJECT_ROOT, output_dir
from .experiments.common import FAMILY_LABELS
from .temporal_process import TEMPORAL_PATTERNS

TEMPLATE = PROJECT_ROOT / "reports" / "technical_report_template.md"
REPORT = PROJECT_ROOT / "reports" / "technical_report.md"
PLACEHOLDER = re.compile(r"\{\{(v|t):([^}]+)\}\}")
MISSING_MARK = "（未計算）"


@dataclass(frozen=True)
class ValueSpec:
    key: str
    table: str  # results/metrics の CSV の名前（拡張子なし）
    query: str  # pandas の query 文字列（空なら全行）
    column: str
    agg: str = "mean"  # mean | max | min | first | count | sum
    fmt: str = "{:.2f}"


def evaluate(spec: ValueSpec, metrics_dir: Path) -> float:
    frame = pd.read_csv(metrics_dir / f"{spec.table}.csv")
    if spec.query:
        frame = frame.query(spec.query)
    if frame.empty:
        raise ValueError(f"{spec.key}: 条件に合う行がない（{spec.table}: {spec.query}）")
    series = frame[spec.column]
    if spec.agg == "first":
        return float(series.iloc[0])
    if spec.agg == "count":
        return float(len(series))
    return float(getattr(series, spec.agg)())


def format_value(spec: ValueSpec, raw: float) -> str:
    if spec.fmt == "percent":
        return f"{raw * 100:.1f}%"
    if spec.fmt == "percent0":
        return f"{raw * 100:.0f}%"
    if spec.fmt == "percent2":
        return f"{raw * 100:.2f}%"
    return spec.fmt.format(raw)


# ---------------------------------------------------------------------- 表
def _md(frame: pd.DataFrame) -> str:
    header = "| " + " | ".join(str(c).replace("|", "\\|") for c in frame.columns) + " |"
    align = "| " + " | ".join("---:" if pd.api.types.is_numeric_dtype(frame[c]) else ":---" for c in frame.columns) + " |"
    rows = []
    for _, row in frame.iterrows():
        cells = []
        for column in frame.columns:
            value = row[column]
            if isinstance(value, float):
                cells.append("—" if np.isnan(value) else f"{value:.3g}" if abs(value) < 1e-3 and value != 0 else f"{value:.2f}")
            else:
                cells.append(str(value).replace("|", "\\|"))  # 検出器名の「|」で表が崩れないように
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join([header, align, *rows])


def _read(metrics_dir: Path, name: str) -> pd.DataFrame:
    return pd.read_csv(metrics_dir / f"{name}.csv")


def _reps(m) -> pd.DataFrame:
    reps = _read(m, "phase1_representatives")
    order = ["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "OR"]
    return reps.set_index("family").reindex(order).dropna(subset=["representative"]).reset_index()


def table_phase1_representatives(m: Path) -> str:
    reps = _reps(m)
    frame = pd.DataFrame({"系統": reps["family"] + " " + reps["family_label"], "代表の設定": reps["representative"], "平均検出率（B1〜B10・1〜16σ_dir・FPR 1%）": reps["mean_detection"]})
    return _md(frame)


def table_phase1_matrix(m: Path, amplitude: float = 4.0) -> str:
    detection = _read(m, "phase1_detection")
    reps = _reps(m)
    names = list(reps["representative"])
    data = detection[(detection["alpha"] == 0.01) & (detection["amplitude"] == amplitude) & (detection["detector"].isin(names + ["Oracle_projection", "Oracle_whitened"]))]
    matrix = data.pivot(index="pattern", columns="detector", values="detection_rate").reindex(index=list(SINGLE_WAFER_PATTERNS), columns=names + ["Oracle_projection", "Oracle_whitened"])
    matrix.columns = [f"{FAMILY_LABELS.get(f, f)}" for f in reps["family"]] + ["理論：射影", "理論：白色化"]
    matrix.insert(0, "パターン", [f"{p} {SINGLE_WAFER_PATTERNS[p]}" for p in matrix.index])
    return _md(matrix.reset_index(drop=True))


def table_phase1_mda(m: Path) -> str:
    mda = _read(m, "phase1_mda")
    reps = _reps(m)
    names = list(reps["representative"])
    data = mda[(mda["alpha"] == 0.01) & mda["detector"].isin(names)]
    matrix = data.pivot(index="pattern", columns="detector", values="mda50").reindex(index=list(SINGLE_WAFER_PATTERNS), columns=names)
    matrix.columns = [FAMILY_LABELS.get(f, f) for f in reps["family"]]
    matrix.insert(0, "パターン", list(matrix.index))
    return _md(matrix.reset_index(drop=True)) + "\n\n（「—」は 16σ_dir でも検出率 50% に届かない）"


def table_phase1_fpr(m: Path) -> str:
    thresholds = _read(m, "phase1_thresholds")
    reps = _reps(m)
    names = [n for n in reps["representative"] if not n.startswith("OR[")] + ["SPE_raw_q90", "SPE_raw_q95", "T2_raw_q95"]
    rows = []
    for name in dict.fromkeys(names):
        for alpha in sorted(thresholds["alpha"].unique(), reverse=True):
            row = thresholds[(thresholds["detector"] == name) & (thresholds["alpha"] == alpha)]
            if row.empty:
                continue
            row = row.iloc[0]
            rows.append({"手法": name, "目標 FPR": f"{alpha:.1%}", "経験的な限界の FPR": f"{row['fpr']:.2%}（{row['fpr_ci_low']:.2%}〜{row['fpr_ci_high']:.2%}）", "理論上の限界の FPR": "—" if pd.isna(row.get("fpr_theoretical", np.nan)) else f"{row['fpr_theoretical']:.2%}"})
    return _md(pd.DataFrame(rows))


def table_pattern_sizes(m: Path) -> str:
    sizes = _read(m, "phase1_pattern_sizes")
    data = sizes[sizes["amplitude"].isin([1.0, 4.0, 16.0])]
    frame = data.pivot(index="pattern", columns="amplitude", values="rms_nm").reindex(list(SINGLE_WAFER_PATTERNS))
    first = sizes.drop_duplicates("pattern").set_index("pattern").reindex(list(SINGLE_WAFER_PATTERNS))
    out = pd.DataFrame({"パターン": [f"{p} {SINGLE_WAFER_PATTERNS[p]}" for p in frame.index], "σ_dir [nm]（ベクトルのノルム）": first["sigma_dir_nm"].to_numpy(), "κ（平均）": first["kappa_mean"].to_numpy(), "RMS 1σ [nm]": frame[1.0].to_numpy(), "RMS 4σ [nm]": frame[4.0].to_numpy(), "RMS 16σ [nm]": frame[16.0].to_numpy()})
    return _md(out)


def table_b10_checks(m: Path) -> str:
    checks = _read(m, "phase1_b10_checks")
    frame = pd.DataFrame({"振幅 [σ_dir]": checks["amplitude"], "平均の差の最大 [nm]": checks["max_abs_mean_diff_nm"], "標準偏差の差の最大 [nm]": checks["max_abs_sd_diff_nm"], "M3S の差の最大 [nm]": checks["max_abs_m3s_diff_nm"], "変化の RMS [nm]": checks["rms_change_nm"], "頭打ちの割合": checks["capped_fraction"]})
    return _md(frame)


def table_b10_permutation(m: Path) -> str:
    perm = _read(m, "phase1_b10_permutation")
    reps = _reps(m)
    names = list(reps["representative"])
    data = perm[(perm["alpha"] == 0.01) & perm["detector"].isin(names)]
    matrix = data.pivot(index="kind", columns="detector", values="detection_rate").reindex(columns=names)
    matrix.columns = [FAMILY_LABELS.get(f, f) for f in reps["family"]]
    labels = {"rot180": "180°回転", "mirror_x": "左右反転", "mirror_y": "上下反転", "shuffle": "無作為な入れ替え"}
    matrix.insert(0, "入れ替え方", [labels.get(k, k) for k in matrix.index])
    return _md(matrix.reset_index(drop=True))


def table_phase2_ranking(m: Path) -> str:
    ranking = _read(m, "phase2_ranking")
    frame = pd.DataFrame(
        {
            "順位": ranking["rank"],
            "検出器": ranking["detector"],
            "平均 RMST 遅延 [枚]": ranking["mean_rmst_delay"],
            "平均検出率（200 枚以内）": ranking["mean_detection_rate"],
            "変化なしの RMST [枚]": ranking["null_rmst_delay"],
            "変化なしの見かけの検出率": ranking["null_detection_rate"],
            "変化点前の誤報の割合": ranking["pre_change_false_alarm_rate"],
        }
    )
    return _md(frame)


def table_phase2_by_pattern(m: Path, value: str = "rmst_delay") -> str:
    delays = _read(m, "phase2_delays")
    data = delays.groupby(["detector", "pattern"])[value].mean().unstack().reindex(columns=list(TEMPORAL_PATTERNS))
    ranking = _read(m, "phase2_ranking")
    data = data.reindex(ranking["detector"])
    data.columns = [f"{p} {TEMPORAL_PATTERNS[p]}" for p in data.columns]
    data.insert(0, "検出器", data.index)
    return _md(data.reset_index(drop=True))


def table_phase2_by_component(m: Path) -> str:
    delays = _read(m, "phase2_delays")
    data = delays.groupby(["detector", "component"])["rmst_delay"].mean().unstack().reindex(columns=list(TEMPORAL_COMPONENTS))
    ranking = _read(m, "phase2_ranking")
    data = data.reindex(ranking["detector"])
    data.insert(0, "検出器", data.index)
    return _md(data.reset_index(drop=True))


def table_phase2_arl0(m: Path) -> str:
    arl = _read(m, "phase2_arl0")
    frame = pd.DataFrame({"検出器": arl["detector"], "管理限界": arl["threshold"], "ARL₀（校正）": arl["arl_calibration"], "ARL₀（独立な確認）": arl["arl"], "95%CI 下限": arl["arl_ci_low"], "95%CI 上限": arl["arl_ci_high"], "打ち切り本数": arl["censored_runs"]})
    return _md(frame)


def table_phase2_amplitude(m: Path, pattern: str) -> str:
    """パターンごとの変化量別の平均 RMST 遅延（6成分の平均）。"""
    delays = _read(m, "phase2_delays")
    ranking = _read(m, "phase2_ranking")
    data = delays[delays["pattern"] == pattern].pivot_table(index="detector", columns="amplitude", values="rmst_delay", aggfunc="mean")
    data = data.reindex(ranking["detector"])
    data.columns = [f"{a:g}σ" for a in data.columns]
    data["変化なし"] = ranking.set_index("detector")["null_rmst_delay"].reindex(data.index).to_numpy()
    data.insert(0, "検出器", data.index)
    label = TEMPORAL_PATTERNS[pattern]
    return _md(data.reset_index(drop=True)) + f"\n\n（{pattern} {label}：変化量ごとの平均 RMST 遅延 [枚]、6成分の平均。未検出は 200 枚として数える）"


def table_phase2_by_component_main(m: Path) -> str:
    """成分ごとの平均 RMST（土台ごとに最良の方式と M3S の Shewhart）。"""
    delays = _read(m, "phase2_delays")
    ranking = _read(m, "phase2_ranking")
    best = ranking.sort_values("mean_rmst_delay").drop_duplicates("base")["detector"].tolist()
    if "M3S_XY|Shewhart" not in best:
        best.append("M3S_XY|Shewhart")
    data = delays[delays["detector"].isin(best)].groupby(["detector", "component"])["rmst_delay"].mean().unstack().reindex(index=best, columns=list(TEMPORAL_COMPONENTS))
    data.insert(0, "検出器", data.index)
    return _md(data.reset_index(drop=True)) + "\n\n（成分ごとの平均 RMST 遅延 [枚]。A1〜A4・全変化量の平均）"


def table_phase2_mdc(m: Path) -> str:
    mdc = _read(m, "phase2_mdc")
    ranking = _read(m, "phase2_ranking")
    data = mdc.groupby(["detector", "pattern"])["mdc90"].median().unstack().reindex(index=ranking["detector"], columns=list(TEMPORAL_PATTERNS))
    data.columns = [f"{p}" for p in data.columns]
    data.insert(0, "検出器", data.index)
    return _md(data.reset_index(drop=True)) + "\n\n（200 枚以内の検出率が 90% に達する最小の変化量 [σ_dir]。6成分の中央値。「—」は 3σ_dir でも届かない成分が半数以上）"


def table_phase2_rho(m: Path) -> str:
    sweep = _read(m, "phase2_rho_sweep")
    sweep = sweep[sweep["pattern"] != "no_change"]
    data = sweep.groupby(["detector", "prewhiten", "rho"])["rmst_delay"].mean().unstack()
    data.columns = [f"ρ = {c:g}" for c in data.columns]
    data = data.reset_index()
    data["prewhiten"] = data["prewhiten"].map({True: "AR(1) 残差", False: "そのまま"})
    data = data.rename(columns={"detector": "検出器", "prewhiten": "入力"})
    return _md(data)


def table_phase3_effects(m: Path) -> str:
    effects = _read(m, "phase3_factor_effects")
    labels = {"density": "計測密度", "layout": "計測配置", "noise_scale": "計測ノイズ", "order": "監視多項式の次数"}
    frame = pd.DataFrame(
        {
            "因子": effects["factor"].map(labels),
            "水準間の検出率の幅（手法×パターンの平均）": effects["sensitivity"],
            "幅の最大（手法×パターン）": effects["max_cell_range"],
            "全体の平均検出率の最小": effects["min_mean_detection"],
            "全体の平均検出率の最大": effects["max_mean_detection"],
        }
    )
    return _md(frame)


def table_phase3_levels(m: Path) -> str:
    single = _read(m, "phase3_single")
    levels = _read(m, "phase3_levels")
    data = single[single["pattern"] != "normal"].groupby(["level", "config"])["detection_rate"].mean().unstack()
    info = levels.drop_duplicates("level").set_index("level")
    order = list(dict.fromkeys(levels["level"]))
    data = data.reindex(order)
    data.insert(0, "点数", info.reindex(order)["n_points"].astype(int).to_numpy())
    data.insert(0, "条件", [_level_label(l) for l in order])
    return _md(data.reset_index(drop=True))


def _level_label(level: str) -> str:
    parts = dict(re.findall(r"(density|noise|order)([^_]+)", level))
    layout = level.split("_noise")[0].split("_", 1)[1]
    names = {"realistic": "実計測風", "uniform": "均等", "d_optimal": "D最適", "i_optimal": "I最適"}
    order = "各手法の次数" if parts.get("order") == "own" else f"{parts.get('order')}次"
    return f"密度 {float(parts['density']):.0%}・{names.get(layout, layout)}・ノイズ {parts['noise']}×・{order}"


def table_phase3_temporal(m: Path) -> str:
    temporal = _read(m, "phase3_temporal")
    temporal = temporal[temporal["pattern"] != "no_change"]
    data = temporal.groupby(["level", "detector"])["rmst_delay"].mean().unstack()
    order = list(dict.fromkeys(temporal["level"]))
    data = data.reindex(order)
    data.insert(0, "条件", [_level_label(l) for l in order])
    return _md(data.reset_index(drop=True))


def table_apc(m: Path, condition: str = "standard") -> str:
    apc = _read(m, "apc_single")
    data = apc[(apc["alignment_condition"] == condition) & (apc["scenario"] != "normal")]
    monitors = ["alignment:M3S", "alignment:T2", "alignment:SPE", "coefficient:MD", "coefficient:SPC", "overlay:M3S", "overlay:T2", "overlay:SPE"]
    data = data[data["monitor"].isin(monitors)].groupby(["correction_order", "scenario", "monitor"])["detection_rate"].mean().unstack().reindex(columns=monitors)
    rms = apc[(apc["alignment_condition"] == condition)].groupby(["correction_order", "scenario"])["true_overlay_rms_nm"].mean()
    data["真の Overlay 残差 RMS [nm]"] = rms.reindex(data.index)
    data.columns = [c.replace("alignment:", "補正前 ").replace("coefficient:", "補正係数 ").replace("overlay:", "残差 ") for c in data.columns]
    data = data.reset_index().rename(columns={"correction_order": "補正次数", "scenario": "シナリオ"})
    return _md(data)


def table_apc_temporal(m: Path) -> str:
    temporal = _read(m, "apc_temporal")
    temporal = temporal[temporal["pattern"] != "no_change"]
    data = temporal.groupby(["detector", "component"])["rmst_delay"].mean().unstack().reindex(columns=["low", "radial", "local"])
    order = sorted(data.index, key=lambda name: (["alignment", "coefficient", "overlay"].index(name.split(":")[0]), name))
    data = data.reindex(order)
    data.index = [n.replace("alignment:", "補正前 ").replace("coefficient:", "補正係数 ").replace("overlay:", "残差 ") for n in data.index]
    data.columns = ["低次（補正で除去）", "Radial（補正で除去）", "局所（補正で残る）"]
    data.insert(0, "監視対象・検出器", data.index)
    return _md(data.reset_index(drop=True))


def table_monitor_info(m: Path) -> str:
    info = _read(m, "phase1_monitor_info")
    rows = []
    for _, row in info.iterrows():
        detail = ""
        if not pd.isna(row.get("pca_components", np.nan)):
            detail = f"主成分 {int(row['pca_components'])} 個（累積寄与率 {row['pca_explained']:.1%}、入力 {int(row['input_dim'])} 次元）"
        elif not pd.isna(row.get("ledoit_wolf_shrinkage", np.nan)):
            detail = f"係数 {int(row['input_dim'])} 個、縮小の強さ {row['ledoit_wolf_shrinkage']:.4f}、条件数 {row['condition_number']:.0f}"
        elif not pd.isna(row.get("poly_order", np.nan)):
            detail = f"{int(row['poly_terms'])} 項 × XY、条件数 {row['condition_number']:.0f}"
        elif not pd.isna(row.get("gpr_X_length_mm", np.nan)):
            detail = f"X：σ_f {row['gpr_X_signal_sd']:.1f} nm・ℓ {row['gpr_X_length_mm']:.0f} mm・σ_shot {row['gpr_X_shot_sd']:.2f}・σ_mark {row['gpr_X_mark_sd']:.2f} nm"
        rows.append({"手法": row["monitor"], "系統": row["family"], "学習で決まった値": detail or "—"})
    return _md(pd.DataFrame(rows))


def table_conditions(config: dict) -> str:
    p1, p2, p3, apc = config["phase1"], config["phase2"], config["phase3"], config["apc"]
    rows = [
        ("Phase 1", "1 Wafer の異常（B1〜B10）", f"学習 {p1['n_train']:,} 枚・校正 {p1['n_calibration']:,}・評価 {p1['n_evaluation']:,}・異常は各条件 {p1['n_replicates']:,} 回、振幅 {p1['amplitudes']}、FPR {p1['alphas']}"),
        ("Phase 2 予備", "λ・k の選定", f"{p2['pilot']['n_series']} 系列 × 300 枚、ARL₀ 校正 {p2['pilot']['arl_calibration_runs']} 本 × {p2['pilot']['arl_calibration_length']} 枚"),
        ("Phase 2 本評価", "経時変化（A1〜A4 × 6成分）", f"{p2['main']['n_series']:,} 系列 × 300 枚、振幅 {p2['amplitudes']}、ARL₀ = {p2['target_arl0']}（校正 {p2['main']['arl_calibration_runs']} 本・確認 {p2['main']['arl_validation_runs']} 本 × {p2['main']['arl_calibration_length']} 枚）"),
        ("Phase 2 ρ", "時系列相関", f"ρ = {p2['rho_sweep']['rho_values']}、{p2['rho_sweep']['patterns']} × {p2['rho_sweep']['components']}、{p2['rho_sweep']['n_series']} 系列"),
        ("Phase 3", "計測条件（単因子＋上位2因子の交互作用）", f"密度 {p3['factors']['density']}、配置 {p3['factors']['layout']}（{p3['layout_density']:.0%}）、ノイズ {p3['factors']['noise_scale']}、次数 {p3['factors']['order']}、各条件 {p3['n_replicates']:,} 回"),
        ("Phase 3 時系列", "経時変化（縮小版）", f"{p3['temporal']['patterns']} × {p3['temporal']['components']} × {p3['temporal']['amplitudes']}、{p3['temporal']['n_series']} 系列"),
        ("APC", "補正による隠蔽", f"補正次数 {apc['correction_orders']}、Alignment {apc['alignment_map']['density']:.0%}（標準）・{apc['sparse_alignment_density']:.1%}＋ノイズ {max(apc['alignment_noise_scales'])}×（過学習条件）、各条件 {apc['n_replicates']:,} 回"),
    ]
    return _md(pd.DataFrame(rows, columns=["段階", "内容", "規模"]))


def references_list(_m: Path) -> str:
    """参考文献（references/references.json が正本）。本文では [id] で引用する。"""
    import json

    refs = json.loads((PROJECT_ROOT / "references" / "references.json").read_text(encoding="utf-8"))["references"]
    lines = []
    for ref in refs:
        place = ref["venue"]
        if ref.get("volume") and ref["itemType"] == "journalArticle":
            place += f", {ref['volume']}" + (f"({ref['issue']})" if ref.get("issue") else "") + (f", {ref['pages']}" if ref.get("pages") else "")
        elif ref.get("pages"):
            place += f", {ref['pages']}"
        if ref.get("isbn"):
            place += f"（ISBN {ref['isbn']}）"
        link = f" https://doi.org/{ref['doi']}" if ref.get("doi") else ""
        lines.append(f"- [{ref['key']}] {'; '.join(ref['authors'])} ({ref['year']}). {ref['title']}. {place}.{link}")
    return "\n".join(lines)


TABLE_BUILDERS = {
    "references": references_list,
    "phase1_representatives": table_phase1_representatives,
    "phase1_matrix": table_phase1_matrix,
    "phase1_mda": table_phase1_mda,
    "phase1_fpr": table_phase1_fpr,
    "pattern_sizes": table_pattern_sizes,
    "b10_checks": table_b10_checks,
    "b10_permutation": table_b10_permutation,
    "phase2_ranking": table_phase2_ranking,
    "phase2_by_pattern": table_phase2_by_pattern,
    "phase2_by_component": table_phase2_by_component,
    "phase2_arl0": table_phase2_arl0,
    "phase2_step": lambda m: table_phase2_amplitude(m, "A1"),
    "phase2_ramp": lambda m: table_phase2_amplitude(m, "A2"),
    "phase2_by_component_main": table_phase2_by_component_main,
    "phase2_mdc": table_phase2_mdc,
    "phase2_rho": table_phase2_rho,
    "phase3_effects": table_phase3_effects,
    "phase3_levels": table_phase3_levels,
    "phase3_temporal": table_phase3_temporal,
    "apc_standard": lambda m: table_apc(m, "standard"),
    "apc_sparse": lambda m: table_apc(m, "sparse_noisy"),
    "apc_temporal": table_apc_temporal,
    "monitor_info": table_monitor_info,
}


def value_specs() -> list[ValueSpec]:
    """レポート本文に埋め込む値（キーは本文の {{v:キー}}）。"""
    from .report_values import VALUE_SPECS

    return VALUE_SPECS


def build_report(config: dict) -> Path:
    metrics_dir = output_dir(config) / "metrics"
    template = TEMPLATE.read_text(encoding="utf-8")
    specs = {spec.key: spec for spec in value_specs()}
    records = []

    missing = []

    def replace(match: re.Match) -> str:
        kind, key = match.group(1), match.group(2).strip()
        try:
            if kind == "t":
                if key == "conditions":
                    return table_conditions(config)
                return TABLE_BUILDERS[key](metrics_dir)
            spec = specs[key]
            raw = evaluate(spec, metrics_dir)
        except (FileNotFoundError, KeyError, ValueError, IndexError) as error:
            # 動作確認用の小さな設定などで計算していない値・表。本報告では出てはいけない（テストで確認）
            missing.append(f"{kind}:{key}（{error}）")
            return MISSING_MARK
        text = format_value(spec, raw)
        records.append({"key": key, "text": text, "raw": raw, "table": spec.table, "query": spec.query, "column": spec.column, "agg": spec.agg, "fmt": spec.fmt})
        return text

    report = PLACEHOLDER.sub(replace, template)
    # 本報告（results/）のときだけ reports/ に書く。動作確認などの別の出力先では、その出力フォルダに書く
    target = REPORT if output_dir(config).resolve() == (PROJECT_ROOT / "results").resolve() else output_dir(config) / "technical_report.md"
    target.write_text(report, encoding="utf-8")
    if missing:
        print(f"[report] この設定では計算していない値・表が {len(missing)} 件あり「{MISSING_MARK}」と書いた：{missing[:3]} …")
    pd.DataFrame(records).drop_duplicates("key").to_csv(metrics_dir / "report_values.csv", index=False, encoding="utf-8")
    return target
