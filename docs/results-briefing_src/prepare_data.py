"""説明資料に載せる数値を、計算結果の CSV から deck_data.json に書き出す（手で書き写さない）。

- 本文の数値の多くは、技術レポートと同じもの（results/metrics/report_values.csv）を使う
- 表とグラフは results/metrics の CSV から直接作る
使い方: ../../.venv/bin/python prepare_data.py
"""
import json
import math
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
METRICS = ROOT / "results" / "metrics"
PATTERNS = ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9", "B10"]
FAMILY_ORDER = ["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "OR"]
COMPONENTS = ["low", "high", "radial", "tangential", "asymmetric", "local"]
BASE_LEVEL = "density1_realistic_noise1_orderown"


def read(name):
    return pd.read_csv(METRICS / f"{name}.csv")


def clean(value):
    """JSON に書けない NaN を None にする。"""
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def records(frame):
    return [{k: clean(v) for k, v in row.items()} for row in frame.to_dict(orient="records")]


def report_values():
    values = read("report_values")
    return {row.key: {"text": row.text, "raw": row.raw} for row in values.itertuples()}


def phase1(reps):
    detection = read("phase1_detection")
    main = detection[detection["alpha"] == 0.01]
    names = list(reps["representative"])
    at4 = main[(main["amplitude"] == 4.0) & main["detector"].isin(names + ["Oracle_projection", "Oracle_whitened"])]
    matrix = at4.pivot(index="pattern", columns="detector", values="detection_rate").reindex(PATTERNS)
    mda = read("phase1_mda")
    mda = mda[(mda["alpha"] == 0.01) & mda["detector"].isin(names)].pivot(index="pattern", columns="detector", values="mda50").reindex(PATTERNS)
    perm = read("phase1_b10_permutation")
    perm = perm[(perm["alpha"] == 0.01) & perm["detector"].isin(names)].pivot(index="kind", columns="detector", values="detection_rate")
    sizes = read("phase1_pattern_sizes")
    first = sizes.drop_duplicates("pattern").set_index("pattern").reindex(PATTERNS)
    curves = {}
    for name in names:
        rows = main[main["detector"] == name]
        curves[name] = {p: rows[rows["pattern"] == p].sort_values("amplitude")["detection_rate"].round(4).tolist() for p in PATTERNS}
    thresholds = read("phase1_thresholds")
    fpr = thresholds[thresholds["detector"].isin(["M3S_XY", "MD_d5", "T2_raw_q99", "SPE_raw_q99", "GPR_rbf_full"])]
    return {
        "matrix4": {p: {d: clean(round(matrix.at[p, d], 4)) for d in matrix.columns} for p in PATTERNS},
        "mda50": {p: {d: clean(round(mda.at[p, d], 2)) if not pd.isna(mda.at[p, d]) else None for d in mda.columns} for p in PATTERNS},
        "permutation": {k: {d: round(perm.at[k, d], 4) for d in perm.columns} for k in perm.index},
        "kappa": {p: round(first.at[p, "kappa_mean"], 2) for p in PATTERNS},
        "sigma_dir": {p: round(first.at[p, "sigma_dir_nm"], 2) for p in PATTERNS},
        "rms4": {p: round(sizes[(sizes["pattern"] == p) & (sizes["amplitude"] == 4)]["rms_nm"].iloc[0], 2) for p in PATTERNS},
        "curves": curves,
        "amplitudes": sorted(main["amplitude"].unique().tolist()),
        "fpr": records(fpr[["detector", "alpha", "fpr", "fpr_theoretical"]]),
    }


def phase2():
    ranking = read("phase2_ranking")
    delays = read("phase2_delays")
    delays = delays[delays["pattern"] != "no_change"]
    best = ranking.sort_values("mean_rmst_delay").drop_duplicates("base")["detector"].tolist()
    if "M3S_XY|Shewhart" not in best:
        best.append("M3S_XY|Shewhart")
    by_component = delays[delays["detector"].isin(best)].groupby(["detector", "component"])["rmst_delay"].mean().unstack()
    by_amp = {}
    for pattern in ["A1", "A2", "A3", "A4"]:
        sub = delays[(delays["pattern"] == pattern) & delays["detector"].isin(best)]
        table = sub.pivot_table(index="detector", columns="amplitude", values="rmst_delay", aggfunc="mean")
        by_amp[pattern] = {d: [round(v, 1) for v in table.loc[d].tolist()] for d in best}
    sweep = read("phase2_rho_sweep")
    sweep = sweep[sweep["pattern"] != "no_change"]
    rho = sweep.groupby(["detector", "prewhiten", "rho"])["rmst_delay"].mean().reset_index()
    rho_table = {}
    for (detector, prewhiten), group in rho.groupby(["detector", "prewhiten"]):
        rho_table.setdefault(detector, {})["prewhiten" if prewhiten else "raw"] = {f"{r:g}": round(v, 1) for r, v in zip(group["rho"], group["rmst_delay"])}
    selection = read("phase2_pilot_selection")
    return {
        "ranking": records(ranking[["rank", "detector", "base", "scheme", "param", "mean_rmst_delay", "mean_detection_rate", "null_rmst_delay", "null_detection_rate", "pre_change_false_alarm_rate"]].round(4)),
        "best": best,
        "by_component": {d: {c: round(by_component.at[d, c], 1) for c in COMPONENTS} for d in best},
        "by_amplitude": by_amp,
        "amplitudes": sorted(delays["amplitude"].unique().tolist()),
        "rho": rho_table,
        "selection": records(selection),
    }


def phase3():
    effects = read("phase3_factor_effects")
    single = read("phase3_single")
    levels = read("phase3_levels").drop_duplicates("level").set_index("level")
    anomalies = single[(single["pattern"] != "normal") & (single["sweep"] == "single_factor")]

    def rate(level, config, pattern=None):
        rows = anomalies[(anomalies["level"] == level) & (anomalies["config"] == config)]
        if pattern:
            rows = rows[rows["pattern"] == pattern]
        return round(rows["detection_rate"].mean(), 3)

    configs = ["M3S_XY", "T2_raw_q99", "GPR_rbf_full", "MD_d5", "OR[top]"]
    density = {f"{d:g}": f"density{d:g}_realistic_noise1_orderown" for d in (1.0, 0.5, 0.25)}
    noise = {f"{n:g}": f"density1_realistic_noise{n:g}_orderown" for n in (0.5, 1.0, 2.0, 3.0)}
    focus = ["all", "B3", "B7", "B8", "B9"]

    def sweep(level_map):
        return {key: {c: {p: rate(level, c, None if p == "all" else p) for p in focus} for c in configs} for key, level in level_map.items()}

    layout = {k: f"density0.25_{k}_noise1_orderown" for k in ("realistic", "uniform", "d_optimal", "i_optimal")}
    temporal = read("phase3_temporal")
    temporal = temporal[temporal["pattern"] != "no_change"]
    temporal_mean = temporal.groupby(["level", "detector"])["rmst_delay"].mean()
    return {
        "effects": records(effects.round(4)),
        "density": sweep(density),
        "noise": sweep(noise),
        "layout": {k: {c: rate(level, c) for c in configs} for k, level in layout.items()},
        "points": {key: int(levels.at[level, "n_points"]) for key, level in density.items()},
        "pca_components": {key: int(levels.at[level, "pca_components_T2_raw_q99"]) for key, level in noise.items()},
        "temporal": {level: {d: round(v, 1) for d, v in temporal_mean.loc[level].items()} for level in temporal["level"].unique()},
    }


def apc():
    single = read("apc_single")
    monitors = ["alignment:M3S", "alignment:T2", "coefficient:MD", "overlay:M3S", "overlay:T2", "overlay:SPE"]
    out = {}
    for condition in ("standard", "sparse_noisy"):
        rows = single[(single["alignment_condition"] == condition) & (single["scenario"] != "normal")]
        table = rows[rows["monitor"].isin(monitors)].groupby(["correction_order", "scenario", "monitor"])["detection_rate"].mean()
        rms = single[single["alignment_condition"] == condition].groupby(["correction_order", "scenario"])["true_overlay_rms_nm"].mean()
        block = {}
        for (order, scenario), value in rms.items():
            entry = block.setdefault(str(order), {}).setdefault(scenario, {"rms": round(value, 2)})
            if scenario != "normal":
                for monitor in monitors:
                    entry[monitor] = round(table.loc[(order, scenario, monitor)], 3)
        out[condition] = block
    temporal = read("apc_temporal")
    temporal = temporal[temporal["pattern"] != "no_change"]
    t = temporal.groupby(["detector", "component"])["rmst_delay"].mean().unstack()
    out["temporal"] = {d: {c: round(t.at[d, c], 1) for c in ("low", "radial", "local")} for d in t.index}
    null = read("apc_temporal")
    null = null[null["pattern"] == "no_change"]["rmst_delay"]
    out["temporal_null"] = [round(null.min(), 1), round(null.max(), 1)]
    return out


def main():
    reps = read("phase1_representatives")
    reps = reps.set_index("family").reindex(FAMILY_ORDER).dropna(subset=["representative"]).reset_index()
    data = {
        "v": report_values(),
        "representatives": records(reps[["family", "family_label", "representative", "mean_detection"]].round(4)),
        "phase1": phase1(reps),
        "phase2": phase2(),
        "phase3": phase3(),
        "apc": apc(),
    }
    (HERE / "deck_data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"deck_data.json: 値 {len(data['v'])} 件、代表 {len(data['representatives'])} 系統")


if __name__ == "__main__":
    main()
