"""Phase 3：計測条件（計測密度・計測配置・計測ノイズ・監視多項式の次数）への依存性（ロバスト性）。

- 1 Wafer の異常検知：Phase 1 の系統別代表の上位 n_top_configs 個 ＋ M3S ＋ 上位の OR 統合。
- 経時変化検知：Phase 2 の順位の上位 n_top_configs 個 ＋ M3S の最良の方式（縮小した条件で）。
まず因子を1つずつ振り（単因子スイープ）、次に性能差の大きかった上位2因子の組み合わせ（交互作用）を調べる。
異常の物理的な大きさは基準マップ（全点・基準ノイズ）の σ_dir で固定する（同じ異常を、点数やノイズを変えて測る）。
多項式を当てはめられない条件（点数・ランク不足）はスキップして記録する。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from ..anomaly_generator import b10_reshape
from ..calibration import OrCombination, empirical_threshold
from ..config import make_rng
from ..evaluation import minimum_detectable_amplitude, rate_with_ci
from ..feature_extraction import polynomial_terms
from ..sampling import build_map
from ..simulation import sample_stationary_coefficients
from .common import build_context, build_single_monitors, fit_monitors, monitor_scores, save_table, training_data
from .phase2 import BASELINE, _conditions, run_temporal_study
from .temporal_engine import TemporalSetup

FACTORS = ("density", "layout", "noise_scale", "order")


@dataclass(frozen=True)
class Level:
    density: float
    layout: str
    noise_scale: float
    order: int | None  # None = 各手法の Phase 1 の次数のまま

    @property
    def name(self) -> str:
        order = "own" if self.order is None else str(self.order)
        return f"density{self.density:g}_{self.layout}_noise{self.noise_scale:g}_order{order}"


def with_order(name: str, order: int | None) -> str:
    """多項式を使う手法の名前を、指定の次数に置き換える（MD_d4 → MD_d5 など）。"""
    if order is None:
        return name
    for prefix in ("SPC_d", "MD_d"):
        if name.startswith(prefix):
            return f"{prefix}{order}"
    if name.startswith(("T2_coef", "SPE_coef")):
        head, tail = name.split("_coef")
        return f"{head}_coef{order}{tail[tail.index('_'):]}"
    return name


def single_factor_levels(p3: dict) -> list[tuple[str, Level]]:
    base = Level(float(p3["base"]["density"]), p3["base"]["layout"], float(p3["base"]["noise_scale"]), None)
    levels = [("base", base)]
    for density in p3["factors"]["density"]:
        if density != base.density:
            levels.append(("density", replace(base, density=float(density))))
    for layout in p3["factors"]["layout"]:
        levels.append(("layout", replace(base, density=float(p3["layout_density"]), layout=layout)))
    for scale in p3["factors"]["noise_scale"]:
        if scale != base.noise_scale:
            levels.append(("noise_scale", replace(base, noise_scale=float(scale))))
    for order in p3["factors"]["order"]:
        levels.append(("order", replace(base, order=int(order))))
    return levels


def _points_for(ctx, level: Level):
    sampling = build_map(ctx.full_points, level.layout, level.density, order=5)
    return ctx.full_points.subset(sampling.point_index), sampling


def evaluate_single_level(ctx, config, level: Level, config_names: list[str]) -> tuple[pd.DataFrame, dict]:
    """ある計測条件で、1 Wafer の検出率（α 固定）を全パターン・全振幅で求める。"""
    p3 = config["phase3"]
    points, sampling = _points_for(ctx, level)
    system = ctx.system(points, noise_scale=level.noise_scale)
    names = {with_order(name, level.order): name for name in config_names}
    orders = sorted({int(n.split("_d")[1]) for n in names if n.startswith(("SPC_d", "MD_d"))} | ({level.order} if level.order else set()))
    mcfg = dict(config["monitoring"])
    mcfg["polynomial_orders"] = orders or mcfg["polynomial_orders"]
    if level.order is not None:
        mcfg["pca_coef_order"] = level.order
    monitors, skipped = build_single_monitors(points, mcfg, include=set(names))
    info = {"level": level.name, "n_points": len(points), "n_shots": len(np.unique(points.shot_index)), "skipped": "; ".join(f"d{s['order']}" for s in skipped)}
    available = [n for n in names if n in monitors]
    train = training_data(ctx, system, int(p3["n_train"]), "phase3", level.name)
    fit_monitors({n: monitors[n] for n in available}, train)
    used = {n: monitors[n] for n in available}
    for name, monitor in used.items():
        if hasattr(monitor, "model"):
            info[f"pca_components_{name}"] = monitor.model.k_  # 寄与率で決まった主成分の数（ノイズの大きさで変わる）

    def draw(purpose: str, n: int) -> tuple[np.ndarray, np.ndarray]:
        """（潜在値、計測値）。潜在係数は条件によらず同じ（CRN）、計測誤差は条件ごと。"""
        rng_coef = make_rng(ctx.seed, "phase3", purpose, "coef")
        rng_noise = make_rng(ctx.seed, "phase3", purpose, "noise", level.name)
        latent = system.latent(sample_stationary_coefficients(system.process, rng_coef, n))
        return latent, latent + system.noise.sample(rng_noise, n, points, ctx.layout.n_shots)

    alpha = float(p3["alpha"])
    cal_values, eval_values = draw("calibration", int(p3["n_calibration"]))[1], draw("evaluation", int(p3["n_evaluation"]))[1]
    cal, ev = monitor_scores(used, cal_values), monitor_scores(used, eval_values)
    column_names = list(used)
    combo = [n for n in column_names if n != BASELINE]
    combiner = OrCombination(combo).fit(cal[:, [column_names.index(n) for n in combo]]) if len(combo) > 1 else None
    if combiner is not None:
        cal = np.column_stack([cal, combiner.transform(cal[:, [column_names.index(n) for n in combo]])])
        ev = np.column_stack([ev, combiner.transform(ev[:, [column_names.index(n) for n in combo]])])
        column_names.append("OR[top]")
    thresholds = [empirical_threshold(cal[:, j], alpha) for j in range(cal.shape[1])]
    rows = []
    for j, name in enumerate(column_names):
        fpr = rate_with_ci(ev[:, j] > thresholds[j])
        rows.append({"level": level.name, "config": names.get(name, name), "monitor": name, "pattern": "normal", "amplitude": 0.0, "detection_rate": fpr["rate"], "ci_low": fpr["ci_low"], "ci_high": fpr["ci_high"], "n": fpr["n"]})

    base_latent, base_values = draw("anomaly_base", int(p3["n_replicates"]))
    for pattern in config["phase1"]["patterns"]:
        params = ctx.anomalies.draw(pattern, make_rng(ctx.seed, "phase3", "anomaly_params", pattern), int(p3["n_replicates"]))
        unit = ctx.anomalies.unit_fields(pattern, params, points)
        for amplitude in p3["amplitudes"]:
            if pattern == "B10":
                values = b10_reshape(base_values, base_latent, unit, float(amplitude))[0]
            else:
                values = base_values + float(amplitude) * unit
            scores = monitor_scores(used, values)
            if combiner is not None:
                scores = np.column_stack([scores, combiner.transform(scores[:, [list(used).index(n) for n in combo]])])
            for j, name in enumerate(column_names):
                result = rate_with_ci(scores[:, j] > thresholds[j])
                rows.append({"level": level.name, "config": names.get(name, name), "monitor": name, "pattern": pattern, "amplitude": float(amplitude), "detection_rate": result["rate"], "ci_low": result["ci_low"], "ci_high": result["ci_high"], "n": result["n"]})
    frame = pd.DataFrame(rows)
    order_label = str(level.order) if level.order else "own"  # 文字列にそろえる（Parquet の列の型を1つにするため）
    for key, value in (("density", level.density), ("layout", level.layout), ("noise_scale", level.noise_scale), ("order", order_label)):
        frame[key] = value
    info.update({"density": level.density, "layout": level.layout, "noise_scale": level.noise_scale, "order": order_label})
    info["min_dof_order5"] = len(points) - len(polynomial_terms(5))
    return frame, info


def _factor_effects(single: pd.DataFrame, levels) -> pd.DataFrame:
    """因子の効き方。上位の手法（M3S・OR 統合を除く）について、手法 × パターンごとに水準間の検出率（全振幅の平均）の幅を求め、
    その平均（sensitivity）で因子を並べる。全パターンの平均だけで比べると、良くなるパターンと悪くなるパターンが打ち消し合うため。
    密度・ノイズの水準には基準（全点・ノイズ 1 倍）も含める。"""
    anomalies = single[(single["pattern"] != "normal") & (single["config"] != BASELINE) & (single["monitor"] != "OR[top]")]
    by_cell = anomalies.groupby(["level", "config", "pattern"], as_index=False)["detection_rate"].mean()
    overall = anomalies.groupby("level")["detection_rate"].mean()
    base_name = next(level.name for f, level in levels if f == "base")
    rows = []
    for factor in FACTORS:
        names = [level.name for f, level in levels if f == factor]
        if factor in ("density", "noise_scale"):
            names = [base_name] + names
        cells = by_cell[by_cell["level"].isin(names)]
        if cells["level"].nunique() < 2:
            continue
        spread = cells.groupby(["config", "pattern"])["detection_rate"].agg(lambda v: v.max() - v.min())
        values = overall.reindex(names).dropna()
        rows.append(
            {
                "factor": factor,
                "sensitivity": spread.mean(),
                "max_cell_range": spread.max(),
                "min_mean_detection": values.min(),
                "max_mean_detection": values.max(),
                "range": values.max() - values.min(),
                "levels": len(values),
            }
        )
    return pd.DataFrame(rows).sort_values("sensitivity", ascending=False).reset_index(drop=True)


def _interaction_levels(p3: dict, factors: list[str]) -> list[Level]:
    base = Level(float(p3["base"]["density"]), p3["base"]["layout"], float(p3["base"]["noise_scale"]), None)
    values = {
        "density": [float(v) for v in p3["factors"]["density"]],
        "layout": list(p3["factors"]["layout"]),
        "noise_scale": [float(v) for v in p3["factors"]["noise_scale"]],
        "order": [int(v) for v in p3["factors"]["order"]],
    }
    a, b = factors
    levels = []
    for va in values[a]:
        for vb in values[b]:
            level = replace(base, **{a: va, b: vb})
            if "layout" in (a, b) and "density" not in (a, b):
                level = replace(level, density=float(p3["layout_density"]))
            if level.layout != "realistic" and level.density >= 1.0:
                continue  # 全点では配置の違いがない
            levels.append(level)
    return levels


def run(config: dict, workers: int | None = None, single: bool = True, temporal: bool = True) -> dict[str, pd.DataFrame]:
    """single：1 Wafer の異常検知（Phase 1 の結果を使う）、temporal：経時変化検知（Phase 2 の結果を使う）。"""
    start = time.time()
    ctx = build_context(config)
    p3 = config["phase3"]
    levels = single_factor_levels(p3)
    results: dict[str, pd.DataFrame] = {}
    if single:
        results.update(_single(ctx, config, levels, start))
    if temporal:
        results.update(_temporal(ctx, config, levels, workers))
    for name, frame in results.items():
        save_table(frame, ctx.out / "metrics" / name)
    print(f"[Phase 3] 完了 {time.time() - start:.0f} 秒", flush=True)
    return results


def _single(ctx, config, levels, start) -> dict[str, pd.DataFrame]:
    p3 = config["phase3"]
    reps = pd.read_csv(ctx.out / "metrics" / "phase1_representatives.csv")
    reps = reps[reps["family"].isin(["M2", "M3", "M4", "M5", "M6"])].sort_values("mean_detection", ascending=False)
    config_names = [BASELINE] + list(reps["representative"].head(int(p3["n_top_configs"])))
    print(f"[Phase 3] 1 Wafer の監視構成: {config_names}", flush=True)
    frames, infos, done = [], [], set()
    for factor, level in levels:
        if level.name in done:
            continue
        frame, info = evaluate_single_level(ctx, config, level, config_names)
        frame["sweep"] = "single_factor"
        frames.append(frame)
        infos.append(info)
        done.add(level.name)
        print(f"[Phase 3] {level.name} {time.time() - start:.0f} 秒", flush=True)
    single = pd.concat(frames, ignore_index=True)
    effects = _factor_effects(single, levels)
    top_factors = list(effects["factor"].head(int(p3["interaction_top_factors"])))
    print(f"[Phase 3] 交互作用を調べる因子: {top_factors}", flush=True)
    interaction_frames = []
    for level in _interaction_levels(p3, top_factors):
        if level.name in done:
            frame = single[single["level"] == level.name].copy()
        else:
            frame, info = evaluate_single_level(ctx, config, level, config_names)
            infos.append(info)
            done.add(level.name)
        frame["sweep"] = "interaction"
        interaction_frames.append(frame)
    interaction = pd.concat(interaction_frames, ignore_index=True)
    level_table = pd.DataFrame([{"factor": f, "level": l.name} for f, l in levels])
    return {
        "phase3_single": single,
        "phase3_factor_effects": effects,
        "phase3_interaction": interaction,
        "phase3_levels": pd.DataFrame(infos).merge(level_table, on="level", how="left"),
        "phase3_mda": _mda(pd.concat([single, interaction], ignore_index=True)),
    }


def _mda(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    anomalies = frame[frame["pattern"] != "normal"].drop_duplicates(["level", "monitor", "pattern", "amplitude"])
    for (level, monitor, pattern), group in anomalies.groupby(["level", "monitor", "pattern"], sort=False):
        group = group.sort_values("amplitude")
        rows.append({"level": level, "monitor": monitor, "config": group["config"].iloc[0], "pattern": pattern, "mda50": minimum_detectable_amplitude(group["amplitude"], group["detection_rate"], 0.5)})
    return pd.DataFrame(rows)


def _temporal(ctx, config, levels, workers) -> dict[str, pd.DataFrame]:
    """経時変化検知のロバスト性（Phase 2 の上位の検出器を、計測条件を変えて再校正・再評価）。"""
    from .phase2 import build_setup

    p3 = config["phase3"]
    settings = dict(p3["temporal"])
    ranking = pd.read_csv(ctx.out / "metrics" / "phase2_ranking.csv")
    if "param" not in ranking:
        params = pd.read_csv(ctx.out / "metrics" / "phase2_delays.csv").drop_duplicates("detector").set_index("detector")["param"]
        ranking["param"] = ranking["detector"].map(params)
    top = ranking[ranking["base"] != BASELINE].head(int(p3["n_top_configs"]))
    baseline = ranking[ranking["base"] == BASELINE].head(1)
    chosen = pd.concat([baseline, top], ignore_index=True)
    print(f"[Phase 3] 経時変化の検出器: {list(chosen['detector'])}", flush=True)
    conditions = _conditions(settings["patterns"], settings["components"], settings["amplitudes"])
    frames, arl_frames, done = [], [], set()
    rho = float(config["phase2"]["rho_values"][0])
    for factor, level in levels:
        if level.name in done:
            continue
        done.add(level.name)
        if level.order is not None and all(with_order(b, level.order) == b for b in chosen["base"]):
            print(f"[Phase 3] {level.name}：多項式を使う検出器がないので経時変化の評価を省略", flush=True)
            continue
        points, _ = _points_for(ctx, level)
        system = ctx.system(points, noise_scale=level.noise_scale, rho=rho)
        bases = [with_order(b, level.order) for b in chosen["base"]]
        lambdas = sorted({float(p) for s, p in zip(chosen["scheme"], chosen["param"]) if str(s).startswith("ewma")})
        ks = sorted({float(p) for s, p in zip(chosen["scheme"], chosen["param"]) if s == "cusum"})
        mcfg = dict(config["monitoring"])
        orders = sorted({int(b.split("_d")[1]) for b in bases if b.startswith(("SPC_d", "MD_d"))})
        if orders:
            mcfg["polynomial_orders"] = orders
        try:
            setup, monitors = build_setup(ctx, config, rho, sorted(set(bases)), lambdas or [0.1], ks or [0.5], ("phase3", "temporal", level.name), system=system, monitoring=mcfg)
        except (KeyError, ValueError) as error:
            print(f"[Phase 3] {level.name} の経時変化はスキップ（{error}）", flush=True)
            continue
        wanted = {_detector_key(with_order(b, level.order), s, p) for b, s, p in zip(chosen["base"], chosen["scheme"], chosen["param"])}
        keep = [d for d in setup.detectors if _detector_key(d.monitor.name, _scheme(d), _param(d)) in wanted]
        setup = TemporalSetup(setup.system, keep, setup.center, None)
        delays, arl, _, _ = run_temporal_study(ctx, config, setup, conditions, settings, ("phase3", "temporal", level.name), workers)
        for frame in (delays, arl):
            frame["level"] = level.name
            frame["factor"] = factor
        frames.append(delays)
        arl_frames.append(arl)
        print(f"[Phase 3] 経時変化 {level.name}", flush=True)
    return {"phase3_temporal": pd.concat(frames, ignore_index=True), "phase3_temporal_arl0": pd.concat(arl_frames, ignore_index=True)}


def _scheme(detector) -> str:
    return detector.scheme + ("-scalar" if getattr(detector, "mode", "") == "scalar" and detector.scheme == "ewma" else "")


def _param(detector) -> float:
    if detector.scheme == "ewma":
        return detector.smoothing
    if detector.scheme == "cusum":
        return detector.k
    return np.nan


def _detector_key(base: str, scheme: str, param) -> tuple:
    value = None if param is None or (isinstance(param, float) and np.isnan(param)) else round(float(param), 6)
    return base, str(scheme), value
