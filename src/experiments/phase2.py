"""Phase 2：経時変化（A1 Step・A2 Ramp・A3 非線形Drift・A4 周期変動）の検知性能。

1. 土台の手法：M3S（ベースライン）＋ Phase 1 の系統別代表のうち上位 n_top_bases 個（M2〜M6 から）。
2. 予備評価（pilot、独立な乱数）：土台ごとに Shewhart・EWMA（λ = 0.05〜0.4）・CUSUM（k）を比べ、
   遅延（RMST）の平均が最小の λ と k を選ぶ。
3. 本評価（main、独立な乱数）：土台 × {Shewhart, EWMA(λ*), CUSUM(k*)} を、ARL₀ をそろえて比べる。
4. 時系列相関 ρ の影響（rho_sweep）：ρ = 0, 0.3, 0.7, 0.95 で本評価の検出器（と AR(1) 残差版）を比べる。
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from ..anomaly_generator import TEMPORAL_COMPONENTS
from ..config import config_hash, make_rng
from ..evaluation import conditional_delays, delay_summary, minimum_detectable_amplitude
from ..temporal_process import TEMPORAL_PATTERNS, temporal_profile
from .common import (
    Context,
    build_context,
    build_single_monitors,
    build_temporal_detectors,
    fit_monitors,
    save_table,
    training_data,
)
from .temporal_engine import (
    NULL_PATTERN,
    Condition,
    TemporalSetup,
    calibrate_thresholds,
    estimate_ar1,
    evaluate_conditions,
    null_condition,
    prewhiten_sequence,
    validate_thresholds,
)

BASELINE = "M3S_XY"


def select_bases(ctx: Context, n_top: int, reference_families=("M2",)) -> list[str]:
    """ベースラインの M3S、参照用の系統（既定は解釈しやすい係数 SPC）の代表、Phase 1 の系統別代表（M2〜M6）の上位 n_top 個。"""
    path = ctx.out / "metrics" / "phase1_representatives.csv"
    if not path.exists():
        raise FileNotFoundError("Phase 1 の結果（phase1_representatives.csv）が必要")
    reps = pd.read_csv(path)
    reps = reps[reps["family"].isin(["M2", "M3", "M4", "M5", "M6"])].sort_values("mean_detection", ascending=False)
    top = list(reps["representative"].head(n_top))
    references = [r for r in reps[reps["family"].isin(reference_families)]["representative"] if r not in top]
    return [BASELINE] + references + top


def unit_fields(ctx: Context, system, components) -> dict[str, np.ndarray]:
    """成分ごとの 1σ_dir の変位（計測マップ上、2N）。σ_dir は基準マップ（全点・基準ノイズ）で決める。"""
    fields = {}
    for component in components:
        params = ctx.anomalies.draw(component, make_rng(ctx.seed, "temporal_component", component), 1)
        fields[component] = ctx.anomalies.unit_fields(component, params, system.points)[0]
    return fields


def component_sigma(ctx: Context, components) -> pd.DataFrame:
    rows = []
    for component in components:
        params = ctx.anomalies.draw(component, make_rng(ctx.seed, "temporal_component", component), 1)
        stats = ctx.anomalies.reference_stats(component, params)
        field = ctx.anomalies.unit_fields(component, params)[0]
        n = len(field) // 2
        rms = float(np.sqrt(np.mean(field[:n] ** 2 + field[n:] ** 2)))
        rows.append({"component": component, "description": TEMPORAL_COMPONENTS[component], "sigma_dir_nm": float(stats["sigma_dir_nm"][0]), "kappa": float(stats["kappa"][0]), "rms_nm_per_sigma": rms})
    return pd.DataFrame(rows)


def build_setup(ctx: Context, config: dict, rho: float, bases, lambdas, ks, key: tuple, prewhiten: bool = False, system=None, monitoring=None):
    """学習（時系列順）→ 監視手法 → 検出器。prewhiten なら AR(1) 残差で学習・監視する。"""
    system = ctx.system(rho=rho) if system is None else system
    train = training_data(ctx, system, int(config["phase2"]["n_train"]), *key, f"rho{rho}")
    center = train.mean(axis=0)
    phi = None
    if prewhiten:
        phi = estimate_ar1(train, center)
        train = prewhiten_sequence(train, center, phi)
        center = train.mean(axis=0)
    monitors, _ = build_single_monitors(system.points, monitoring or config["monitoring"], include=set(bases))
    fit_monitors(monitors, train)
    detectors = build_temporal_detectors(monitors, bases, lambdas, ks, shewhart=True)
    for detector in detectors:
        detector.fit(train)
    return TemporalSetup(system, detectors, center, phi), monitors


def _conditions(patterns, components, amplitudes) -> list[Condition]:
    return [Condition(p, c, float(a)) for p in patterns for c in components for a in amplitudes]


def run_temporal_study(ctx, config, setup, conditions, settings: dict, key: tuple, workers: int, example_condition=None, fields=None):
    """校正 → 確認 → 評価をまとめて行い、遅延の集計表などを返す。fields を省くと成分の 1σ の変位を計測マップ上で作る。"""
    p2 = config["phase2"]
    seed = ctx.seed
    target = float(p2["target_arl0"])
    thresholds, achieved = calibrate_thresholds(setup, seed, key, int(settings["arl_calibration_runs"]), int(settings["arl_calibration_length"]), target, workers=workers)
    validation = []
    if settings.get("arl_validation_runs"):
        validation = validate_thresholds(setup, thresholds, seed, key, int(settings["arl_validation_runs"]), int(settings["arl_validation_length"]), workers=workers)
    if fields is None:
        fields = unit_fields(ctx, setup.system, sorted({c.component for c in conditions}))
    conditions = list(conditions) + [null_condition()]
    results, example = evaluate_conditions(
        setup, thresholds, conditions, fields, p2["temporal_params"], seed, key, int(settings["n_series"]), int(p2["series_length"]), int(p2["onset"]),
        block_size=int(p2.get("block_size", 1000)), workers=workers, example_condition=example_condition,
    )
    window = int(p2["series_length"]) - int(p2["onset"]) + 1
    rng = make_rng(seed, *key, "bootstrap")
    rows = []
    info = {d.name: d for d in setup.detectors}
    for condition, (delays, before) in results.items():
        for j, name in enumerate(setup.names):
            # 変化点より前に誤報が出た系列は遅延の集計から除く（条件付き期待遅延）
            kept, pre_rate = conditional_delays(delays[:, j], before[:, j])
            summary = delay_summary(kept, window, rng)
            detector = info[name]
            summary.update(
                {
                    "detector": name,
                    "base": detector.monitor.name,
                    "scheme": detector.scheme + ("-scalar" if getattr(detector, "mode", "") == "scalar" and detector.scheme == "ewma" else ""),
                    "param": getattr(detector, "smoothing", getattr(detector, "k", np.nan)) if detector.scheme != "shewhart" else np.nan,
                    "pattern": condition.pattern,
                    "component": condition.component,
                    "amplitude": condition.amplitude,
                    "detection_rate_50": float(np.mean(kept <= 50)),
                    "pre_change_false_alarm_rate": pre_rate,
                    "threshold": thresholds[name],
                }
            )
            rows.append(summary)
    arl_rows = []
    for row in validation or [{"detector": n, "threshold": thresholds[n]} for n in setup.names]:
        row = dict(row)
        row["arl_calibration"] = achieved[row["detector"]]
        arl_rows.append(row)
    return pd.DataFrame(rows), pd.DataFrame(arl_rows), results, example


def minimum_detectable_change(delays: pd.DataFrame, level: float = 0.9) -> pd.DataFrame:
    rows = []
    delays = delays[delays["pattern"] != NULL_PATTERN]
    for (detector, pattern, component), group in delays.groupby(["detector", "pattern", "component"], sort=False):
        group = group.sort_values("amplitude")
        rows.append(
            {
                "detector": detector,
                "base": group["base"].iloc[0],
                "scheme": group["scheme"].iloc[0],
                "pattern": pattern,
                "component": component,
                "mdc90": minimum_detectable_amplitude(group["amplitude"], group["detection_rate"], level),
                "mdc50": minimum_detectable_amplitude(group["amplitude"], group["detection_rate"], 0.5),
            }
        )
    return pd.DataFrame(rows)


def select_parameters(pilot: pd.DataFrame) -> pd.DataFrame:
    """土台ごとに、EWMA の λ と CUSUM の k を平均 RMST 遅延が最小のものに決める。"""
    pilot = pilot[pilot["pattern"] != NULL_PATTERN]
    mean_delay = pilot.groupby(["base", "scheme", "param", "detector"], as_index=False, dropna=False)["rmst_delay"].mean()
    rows = []
    for (base, scheme), group in mean_delay.groupby(["base", "scheme"], sort=False):
        best = group.sort_values("rmst_delay").iloc[0]
        rows.append({"base": base, "scheme": scheme, "param": best["param"], "detector": best["detector"], "mean_rmst_delay": best["rmst_delay"]})
    return pd.DataFrame(rows)


def run(config: dict, workers: int | None = None, stages=("pilot", "main", "rho_sweep"), rho_variants=("raw", "prewhiten")) -> dict[str, pd.DataFrame]:
    """rho_variants：ρ の比較で計算する入力（raw＝計測値そのまま、prewhiten＝AR(1) 残差）。一部だけ計算したときは既存の結果と合わせる。"""
    start = time.time()
    workers = int(config.get("workers", 1) if workers is None else workers)
    ctx = build_context(config)
    p2 = config["phase2"]
    mcfg = config["monitoring"]
    bases = select_bases(ctx, int(p2["n_top_bases"]), tuple(p2.get("reference_families", ["M2"])))
    print(f"[Phase 2] 土台の手法: {bases}", flush=True)
    rho = float(p2["rho_values"][0])
    results: dict[str, pd.DataFrame] = {}
    results["phase2_components"] = component_sigma(ctx, p2["components"])
    conditions = _conditions(p2["patterns"], p2["components"], p2["amplitudes"])
    selection_path = ctx.out / "metrics" / "phase2_pilot_selection.csv"

    if "pilot" in stages:
        setup, _ = build_setup(ctx, config, rho, bases, mcfg["ewma_lambdas"], mcfg["cusum_k"], ("phase2", "pilot"))
        pilot, pilot_arl, _, _ = run_temporal_study(ctx, config, setup, conditions, p2["pilot"], ("phase2", "pilot", f"rho{rho}"), workers)
        results["phase2_pilot_delays"] = pilot
        results["phase2_pilot_arl0"] = pilot_arl
        results["phase2_pilot_selection"] = select_parameters(pilot)
        for name in ("phase2_pilot_delays", "phase2_pilot_arl0", "phase2_pilot_selection"):
            save_table(results[name], ctx.out / "metrics" / name)
        print(f"[Phase 2] 予備評価 {time.time() - start:.0f} 秒", flush=True)
    selection = pd.read_csv(selection_path)

    def chosen(scheme):
        return {row["base"]: float(row["param"]) for _, row in selection[selection["scheme"].str.startswith(scheme)].iterrows()}

    lam_by_base, k_by_base = chosen("ewma"), chosen("cusum")
    if "main" in stages:
        setup = _setup_with_selected(ctx, config, rho, bases, lam_by_base, k_by_base, ("phase2", "main"))
        example = Condition("A2", "low", 1.0)
        delays, arl, raw, trace = run_temporal_study(ctx, config, setup, conditions, p2["main"], ("phase2", "main", f"rho{rho}"), workers, example_condition=example)
        delays["rho"] = rho
        arl["rho"] = rho
        results["phase2_delays"] = delays
        results["phase2_arl0"] = arl
        results["phase2_mdc"] = minimum_detectable_change(delays)
        results["phase2_ranking"] = _ranking(delays)
        for name in ("phase2_components", "phase2_delays", "phase2_arl0", "phase2_mdc", "phase2_ranking"):
            save_table(results[name], ctx.out / "metrics" / name)
        _save_example(ctx, setup, trace, example, config, arl)
        np.savez_compressed(ctx.cache / f"phase2_main_delays_{config_hash(config['phase2'])}.npz", **{f"{c.pattern}|{c.component}|{c.amplitude}": d for c, (d, _) in raw.items()}, names=np.array(setup.names))
        print(f"[Phase 2] 本評価 {time.time() - start:.0f} 秒", flush=True)

    if "rho_sweep" in stages:
        sweep = p2["rho_sweep"]
        sweep_conditions = _conditions(sweep["patterns"], sweep["components"], p2["amplitudes"])
        frames, arl_frames = [], []
        for rho_value in sweep["rho_values"]:
            variants = ([False] if "raw" in rho_variants else []) + ([True] if "prewhiten" in rho_variants and sweep.get("prewhiten") and rho_value > 0 else [])
            for prewhiten in variants:
                setup = _setup_with_selected(ctx, config, float(rho_value), bases, lam_by_base, k_by_base, ("phase2", "rho_sweep"), prewhiten=prewhiten)
                delays, arl, _, _ = run_temporal_study(ctx, config, setup, sweep_conditions, sweep, ("phase2", "rho_sweep", f"rho{rho_value}"), workers)
                for frame in (delays, arl):
                    frame["rho"] = float(rho_value)
                    frame["prewhiten"] = prewhiten
                    frame["ar1_phi"] = setup.prewhiten_phi if prewhiten else np.nan
                frames.append(delays)
                arl_frames.append(arl)
                print(f"[Phase 2] ρ={rho_value} 残差={prewhiten} {time.time() - start:.0f} 秒", flush=True)
        results["phase2_rho_sweep"] = pd.concat(frames, ignore_index=True)
        results["phase2_rho_sweep_arl0"] = pd.concat(arl_frames, ignore_index=True)
        if set(rho_variants) != {"raw", "prewhiten"}:
            # 計算しなかった入力の結果は前回の計算から引き継ぐ
            for name in ("phase2_rho_sweep", "phase2_rho_sweep_arl0"):
                path = ctx.out / "metrics" / f"{name}.parquet"
                if path.exists():
                    old = pd.read_parquet(path)
                    computed = set(map(bool, results[name]["prewhiten"]))
                    old = old[~old["prewhiten"].astype(bool).isin(computed)]
                    results[name] = pd.concat([old, results[name]], ignore_index=True)
        for name in ("phase2_rho_sweep", "phase2_rho_sweep_arl0"):
            save_table(results[name], ctx.out / "metrics" / name)
    print(f"[Phase 2] 完了 {time.time() - start:.0f} 秒", flush=True)
    return results


def _setup_with_selected(ctx, config, rho, bases, lam_by_base, k_by_base, key, prewhiten=False):
    """土台ごとに選んだ λ・k だけの検出器（Shewhart・EWMA・CUSUM 各1つ）を作る。"""
    lambdas = sorted(set(lam_by_base.values()))
    ks = sorted(set(k_by_base.values()))
    setup, monitors = build_setup(ctx, config, rho, bases, lambdas, ks, key, prewhiten=prewhiten)
    keep = []
    for detector in setup.detectors:
        base = detector.monitor.name
        if detector.scheme == "shewhart":
            keep.append(detector)
        elif detector.scheme == "ewma" and np.isclose(detector.smoothing, lam_by_base.get(base, np.nan)):
            keep.append(detector)
        elif detector.scheme == "cusum" and np.isclose(detector.k, k_by_base.get(base, np.nan)):
            keep.append(detector)
    return TemporalSetup(setup.system, keep, setup.center, setup.prewhiten_phi)


def _ranking(delays: pd.DataFrame) -> pd.DataFrame:
    """全条件の平均 RMST 遅延（小さいほど良い）と平均検出率で並べる。"""
    null = delays[delays["pattern"] == NULL_PATTERN].set_index("detector")
    delays = delays[delays["pattern"] != NULL_PATTERN]
    summary = delays.groupby(["detector", "base", "scheme", "param"], as_index=False, dropna=False).agg(mean_rmst_delay=("rmst_delay", "mean"), mean_detection_rate=("detection_rate", "mean"))
    summary["null_rmst_delay"] = summary["detector"].map(null["rmst_delay"])
    summary["null_detection_rate"] = summary["detector"].map(null["detection_rate"])
    summary["pre_change_false_alarm_rate"] = summary["detector"].map(null["pre_change_false_alarm_rate"])
    summary = summary.sort_values("mean_rmst_delay").reset_index(drop=True)
    summary["rank"] = np.arange(1, len(summary) + 1)
    return summary


def _save_example(ctx, setup, trace, condition, config, arl) -> None:
    """Figure 6 用：1 系列の各検出器の統計量と管理限界、真の変化量。"""
    if trace is None:
        return
    p2 = config["phase2"]
    profile = condition.amplitude * temporal_profile(condition.pattern, int(p2["series_length"]), int(p2["onset"]), p2["temporal_params"])
    thresholds = arl.set_index("detector")["threshold"].reindex(setup.names).to_numpy()
    np.savez_compressed(
        ctx.out / "samples" / "phase2_example.npz",
        statistics=trace,
        names=np.array(setup.names),
        thresholds=thresholds,
        true_change_sigma=profile,
        pattern=condition.pattern,
        component=condition.component,
        amplitude=condition.amplitude,
    )


__all__ = ["run", "TEMPORAL_PATTERNS"]
