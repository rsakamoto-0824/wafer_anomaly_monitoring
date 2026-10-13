"""Phase 1：1 Wafer の面内形状異常（B1〜B10）の検知性能。

流れ
1. 時系列順の正常データ（n_train 枚）で全手法を学習する。
2. 正常系列（history 枚 + 評価する1枚）を独立に n_calibration 本・n_evaluation 本つくり、最後の Wafer の
   スコアを集める。EWMA・CUSUM は前の history 枚で状態を進めてから最後の Wafer を判定する
   （Wafer の流れの中に単発の異常が1枚だけ入ったときに、その Wafer で警報が出るか）。
3. 校正用のスコアで誤報率 α（5%・1%・0.1%）の管理限界を決め、評価用の正常データで実際の誤報率を確かめる。
4. 異常：n_replicates 本の正常系列の最後の Wafer に異常を足す。異常の種類・振幅・手法によらず同じ正常 Wafer と
   同じ異常パラメータを使う（Common Random Numbers）。
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from scipy import stats

from ..anomaly_generator import (
    B10_PERMUTATIONS,
    SHAPE_DESCRIPTIONS,
    SINGLE_WAFER_PATTERNS,
    anomaly_size_summary,
    b10_permute,
    b10_reshape,
)
from ..calibration import OrCombination, empirical_threshold
from ..config import config_hash, make_rng
from ..evaluation import (
    auc_interval,
    average_precision,
    average_precision_interval,
    minimum_detectable_amplitude,
    rate_with_ci,
    roc_auc,
)
from ..feature_extraction import m3s_by_axis
from ..simulation import split_axes
from .common import (
    FAMILY_LABELS,
    Context,
    SequenceRunner,
    build_context,
    build_single_monitors,
    build_temporal_detectors,
    detector_table,
    fit_monitors,
    monitor_scores,
    save_table,
    training_data,
)

CACHE_SECTIONS = ("seed", "wafer", "marks", "normal_process", "noise", "anomaly", "monitoring", "phase1")


def _setup(config: dict):
    ctx = build_context(config)
    p1 = config["phase1"]
    system = ctx.system()
    train = training_data(ctx, system, p1["n_train"], "phase1")
    monitors, skipped = build_single_monitors(ctx.full_points, config["monitoring"])
    fit_monitors(monitors, train)
    mcfg = config["monitoring"]
    detectors = build_temporal_detectors(
        monitors, mcfg["temporal_bases"], mcfg["ewma_lambdas"], mcfg["cusum_k"], shewhart=False, md_scalar=mcfg.get("md_scalar_ewma", False)
    )
    for detector in detectors:
        detector.fit(train)
    runner = SequenceRunner(system, detectors, train.mean(axis=0))
    return ctx, system, train, monitors, skipped, detectors, runner


def _normal_block(runner: SequenceRunner, monitors: dict, seed: int, purpose: str, block: int, n_series: int, history: int) -> np.ndarray:
    rng = make_rng(seed, "phase1", purpose, block)
    maps, states, _, values = runner.run_history(rng, n_series, history)
    return np.column_stack([monitor_scores(monitors, values), runner.final_statistics(maps, states, values)])


def _normal_scores(ctx, runner, monitors, purpose: str, n_total: int, p1: dict, workers: int, cache_dir) -> np.ndarray:
    block_size = int(p1["block_size"])
    n_blocks = int(np.ceil(n_total / block_size))
    sizes = [min(block_size, n_total - b * block_size) for b in range(n_blocks)]
    todo = [b for b in range(n_blocks) if not (cache_dir / f"{purpose}_{b:03d}.npy").exists()]
    if todo:
        results = Parallel(n_jobs=workers)(
            delayed(_normal_block)(runner, monitors, ctx.seed, purpose, b, sizes[b], p1["history_length"]) for b in todo
        )
        for b, result in zip(todo, results):
            np.save(cache_dir / f"{purpose}_{b:03d}.npy", result)
    return np.concatenate([np.load(cache_dir / f"{purpose}_{b:03d}.npy") for b in range(n_blocks)])


def _anomaly_scores(ctx: Context, runner, monitors, p1: dict):
    """CRN：同じ正常 Wafer・同じ異常パラメータで、全パターン・全振幅・全手法のスコアを求める。"""
    n_rep = int(p1["n_replicates"])
    rng = make_rng(ctx.seed, "phase1", "anomaly_base")
    maps, states, latent, values = runner.run_history(rng, n_rep, p1["history_length"])
    base_scores = np.column_stack([monitor_scores(monitors, values), runner.final_statistics(maps, states, values)])
    amplitudes = [float(a) for a in p1["amplitudes"]]
    patterns = list(p1["patterns"])
    n_detectors = len(monitors) + len(runner.detectors)
    scores = np.empty((len(patterns), len(amplitudes), n_rep, n_detectors))
    size_rows, b10_rows, examples = [], [], {"base_latent": latent[:4], "base_measured": values[:4]}
    gen = ctx.anomalies
    for i, pattern in enumerate(patterns):
        params = gen.draw(pattern, make_rng(ctx.seed, "phase1", "anomaly_params", pattern), n_rep)
        reference = gen.reference_stats(pattern, params)
        unit = gen.unit_fields(pattern, params)
        for j, amplitude in enumerate(amplitudes):
            if pattern == "B10":
                anomalous, capped = b10_reshape(values, latent, unit, amplitude)
                b10_rows.append({**_b10_check(values, anomalous, amplitude), "capped_fraction": float(capped.any(axis=1).mean())})
                displacement = anomalous - values
            else:
                displacement = amplitude * unit
                anomalous = values + displacement
            scores[i, j] = np.column_stack([monitor_scores(monitors, anomalous), runner.final_statistics(maps, states, anomalous)])
            size = anomaly_size_summary(displacement)
            size_rows.append(
                {
                    "pattern": pattern,
                    "amplitude": amplitude,
                    "sigma_dir_nm": float(reference["sigma_dir_nm"].mean()),
                    "kappa_mean": float(reference["kappa"].mean()),
                    "rms_nm": size["rms_nm"],
                    "max_nm": size["max_nm"],
                }
            )
            examples[f"{pattern}_a{amplitude:g}_measured"] = anomalous[:4]
            examples[f"{pattern}_a{amplitude:g}_displacement"] = displacement[:4]
        examples[f"{pattern}_kappa"] = reference["kappa"]
    perm_kinds = list(p1.get("b10_permutations", []))
    perm_scores = np.empty((len(perm_kinds), n_rep, n_detectors))
    perm_rows = []
    for i, kind in enumerate(perm_kinds):
        permuted = b10_permute(values, ctx.full_points, kind, make_rng(ctx.seed, "phase1", "perm", kind))
        perm_scores[i] = np.column_stack([monitor_scores(monitors, permuted), runner.final_statistics(maps, states, permuted)])
        check = _b10_check(values, permuted, np.nan)
        check["kind"] = kind
        check["multiset_identical"] = bool(
            np.all(np.sort(split_axes(values)[0], axis=1) == np.sort(split_axes(permuted)[0], axis=1))
            and np.all(np.sort(split_axes(values)[1], axis=1) == np.sort(split_axes(permuted)[1], axis=1))
        )
        perm_rows.append(check)
        examples[f"perm_{kind}_measured"] = permuted[:4]
    examples["base_scores"] = base_scores
    return scores, perm_scores, pd.DataFrame(size_rows), pd.DataFrame(b10_rows), pd.DataFrame(perm_rows), examples


def _b10_check(before: np.ndarray, after: np.ndarray, amplitude: float) -> dict:
    """平均・標準偏差・M3S が X・Y それぞれで一致しているか（最大の差）。"""
    bx, by = split_axes(before)
    ax, ay = split_axes(after)
    mean_diff = max(np.abs(bx.mean(1) - ax.mean(1)).max(), np.abs(by.mean(1) - ay.mean(1)).max())
    sd_diff = max(np.abs(bx.std(1, ddof=1) - ax.std(1, ddof=1)).max(), np.abs(by.std(1, ddof=1) - ay.std(1, ddof=1)).max())
    m3s_diff = float(np.abs(m3s_by_axis(before) - m3s_by_axis(after)).max())
    change = np.sqrt(np.mean((after - before) ** 2))
    return {"amplitude": amplitude, "max_abs_mean_diff_nm": float(mean_diff), "max_abs_sd_diff_nm": float(sd_diff), "max_abs_m3s_diff_nm": m3s_diff, "rms_change_nm": float(change)}


# ---------------------------------------------------------------------- 集計
def _add_combinations(names, cal, ev, anomaly, perm, combinations):
    rows = []
    for combo in combinations:
        index = [names.index(name) for name in combo]
        combiner = OrCombination(combo).fit(cal[:, index])
        name = "OR[" + "+".join(combo) + "]"
        names.append(name)
        cal = np.column_stack([cal, combiner.transform(cal[:, index])])
        ev = np.column_stack([ev, combiner.transform(ev[:, index])])
        flat = anomaly[..., index].reshape(-1, len(index))
        anomaly = np.concatenate([anomaly, combiner.transform(flat).reshape(anomaly.shape[:-1] + (1,))], axis=-1)
        flat = perm[..., index].reshape(-1, len(index))
        perm = np.concatenate([perm, combiner.transform(flat).reshape(perm.shape[:-1] + (1,))], axis=-1)
        rows.append({"detector": name, "family": "OR", "base": "+".join(combo), "scheme": "or", "param": np.nan})
    return names, cal, ev, anomaly, perm, pd.DataFrame(rows)


def summarize(ctx: Context, config: dict, data: dict, monitors: dict) -> dict[str, pd.DataFrame]:
    p1 = config["phase1"]
    names = list(data["names"])
    table = data["table"]
    cal, ev, anomaly, perm = data["cal"], data["eval"], data["anomaly"], data["perm"]
    names, cal, ev, anomaly, perm, combo_table = _add_combinations(names, cal, ev, anomaly, perm, config["monitoring"].get("combinations", []))
    table = pd.concat([table, combo_table], ignore_index=True)
    alphas = [float(a) for a in p1["alphas"]]
    amplitudes = [float(a) for a in p1["amplitudes"]]
    patterns = list(p1["patterns"])

    threshold_rows, detection_rows, auc_rows, perm_rows = [], [], [], []
    rng = make_rng(ctx.seed, "phase1", "bootstrap")
    for d, name in enumerate(names):
        info = table.set_index("detector").loc[name]
        for alpha in alphas:
            threshold = empirical_threshold(cal[:, d], alpha)
            fpr = rate_with_ci(ev[:, d] > threshold)
            row = {"detector": name, "family": info["family"], "alpha": alpha, "threshold": threshold, "fpr": fpr["rate"], "fpr_ci_low": fpr["ci_low"], "fpr_ci_high": fpr["ci_high"], "n_eval": fpr["n"]}
            monitor = monitors.get(name)
            theoretical = monitor.theoretical_threshold(alpha) if monitor is not None else None
            if theoretical is not None:
                theo = rate_with_ci(ev[:, d] > theoretical)
                row.update({"threshold_theoretical": theoretical, "fpr_theoretical": theo["rate"], "fpr_theoretical_ci_low": theo["ci_low"], "fpr_theoretical_ci_high": theo["ci_high"]})
            threshold_rows.append(row)
            for i, pattern in enumerate(patterns):
                for j, amplitude in enumerate(amplitudes):
                    result = rate_with_ci(anomaly[i, j, :, d] > threshold)
                    detection_rows.append({"detector": name, "family": info["family"], "base": info["base"], "scheme": info["scheme"], "param": info["param"], "pattern": pattern, "amplitude": amplitude, "alpha": alpha, "detection_rate": result["rate"], "ci_low": result["ci_low"], "ci_high": result["ci_high"], "n": result["n"]})
            for k, kind in enumerate(p1.get("b10_permutations", [])):
                result = rate_with_ci(perm[k, :, d] > threshold)
                perm_rows.append({"detector": name, "family": info["family"], "kind": kind, "alpha": alpha, "detection_rate": result["rate"], "ci_low": result["ci_low"], "ci_high": result["ci_high"], "n": result["n"]})
        for i, pattern in enumerate(patterns):
            for j, amplitude in enumerate(amplitudes):
                positive = anomaly[i, j, :, d]
                auc = roc_auc(ev[:, d], positive)
                lo, hi = auc_interval(auc, len(positive), len(ev))
                ap = average_precision(ev[:, d], positive)
                ap_lo, ap_hi = average_precision_interval(ev[:, d], positive, rng, int(p1.get("ap_bootstrap", 200)))
                auc_rows.append({"detector": name, "family": info["family"], "pattern": pattern, "amplitude": amplitude, "roc_auc": auc, "roc_auc_ci_low": lo, "roc_auc_ci_high": hi, "pr_auc": ap, "pr_auc_ci_low": ap_lo, "pr_auc_ci_high": ap_hi, "prevalence": len(positive) / (len(positive) + len(ev))})

    detection = pd.DataFrame(detection_rows)
    detection = pd.concat([detection, _oracle_rows(data["kappa"], patterns, amplitudes, alphas, p1["n_replicates"])], ignore_index=True)
    mda_rows = []
    for (name, pattern, alpha), group in detection.groupby(["detector", "pattern", "alpha"], sort=False):
        group = group.sort_values("amplitude")
        mda_rows.append({"detector": name, "family": group["family"].iloc[0], "pattern": pattern, "alpha": alpha, "mda50": minimum_detectable_amplitude(group["amplitude"], group["detection_rate"], 0.5), "mda90": minimum_detectable_amplitude(group["amplitude"], group["detection_rate"], 0.9)})
    result = {
        "phase1_detectors": table,
        "phase1_thresholds": pd.DataFrame(threshold_rows),
        "phase1_detection": detection,
        "phase1_auc": pd.DataFrame(auc_rows),
        "phase1_mda": pd.DataFrame(mda_rows),
        "phase1_b10_permutation": pd.DataFrame(perm_rows),
    }
    result.update(_rankings(detection, table, float(p1["main_alpha"])))
    return result


def _oracle_rows(kappa: dict, patterns, amplitudes, alphas, n_rep) -> pd.DataFrame:
    """参考：方向を知っている検定の理論上の検出率。
    - Oracle_projection：異常方向への射影の片側管理図 Φ(a − z_α)（σ_dir 正規化の定義上、全パターン共通）
    - Oracle_whitened  ：白色化した方向の尤度比検定 Φ(a κ − z_α)（パターンの相関構造を使う最良の検定）
    """
    rows = []
    for alpha in alphas:
        z_alpha = stats.norm.isf(alpha)
        for pattern in patterns:
            for amplitude in amplitudes:
                projection = float(stats.norm.sf(z_alpha - amplitude))
                whitened = float(np.mean(stats.norm.sf(z_alpha - amplitude * kappa[pattern])))
                for name, value in (("Oracle_projection", projection), ("Oracle_whitened", whitened)):
                    rows.append({"detector": name, "family": "Oracle", "base": name, "scheme": "theory", "param": np.nan, "pattern": pattern, "amplitude": amplitude, "alpha": alpha, "detection_rate": value, "ci_low": np.nan, "ci_high": np.nan, "n": n_rep})
    return pd.DataFrame(rows)


def _rankings(detection: pd.DataFrame, table: pd.DataFrame, main_alpha: float) -> dict[str, pd.DataFrame]:
    """手法の平均検出率（B1〜B10 × 全振幅、主要な α）で、系統ごとの代表と順位を決める。"""
    main = detection[(detection["alpha"] == main_alpha) & (detection["family"] != "Oracle")]
    overall = main.groupby(["detector", "family"], as_index=False)["detection_rate"].mean().rename(columns={"detection_rate": "mean_detection"})
    overall = overall.sort_values("mean_detection", ascending=False).reset_index(drop=True)
    overall["rank"] = np.arange(1, len(overall) + 1)
    representatives = []
    for family, group in overall.groupby("family", sort=False):
        if family == "M1":
            best = group[group["detector"] == "M3S_XY"].iloc[0]  # ベースラインは XY 統合判定に固定
        else:
            best = group.iloc[0]
        representatives.append({"family": family, "family_label": FAMILY_LABELS.get(family, family), "representative": best["detector"], "mean_detection": best["mean_detection"]})
    representatives = pd.DataFrame(representatives).sort_values("mean_detection", ascending=False).reset_index(drop=True)
    by_pattern = main.groupby(["pattern", "detector", "family"], as_index=False)["detection_rate"].mean()
    winners = by_pattern.sort_values("detection_rate", ascending=False).groupby("pattern", sort=False).head(3)
    return {"phase1_ranking": overall, "phase1_representatives": representatives, "phase1_pattern_winners": winners.sort_values(["pattern", "detection_rate"], ascending=[True, False])}


def monitor_info(monitors: dict, skipped: list) -> pd.DataFrame:
    rows = []
    for name, monitor in monitors.items():
        row = {"monitor": name, "family": monitor.family}
        if hasattr(monitor, "model"):
            row.update({"pca_components": monitor.model.k_, "pca_explained": monitor.model.explained_, "input_dim": len(monitor.model.mean_)})
        if hasattr(monitor, "shrinkage_"):
            row.update({"ledoit_wolf_shrinkage": monitor.shrinkage_, "jitter": monitor.jitter_, "input_dim": len(monitor.mean_)})
        if hasattr(monitor, "params_"):
            for axis, params in zip("XY", monitor.params_):
                for key, value in params.items():
                    row[f"gpr_{axis}_{key}"] = value
        if hasattr(monitor, "poly"):
            ident = monitor.poly.identifiability
            row.update({"poly_order": monitor.poly.order, "poly_terms": ident.n_terms, "n_points": ident.n_points, "condition_number": ident.condition_number})
        rows.append(row)
    for item in skipped:
        rows.append({"monitor": f"poly_d{item['order']}", "family": "skipped", "note": item["reason"], "n_points": item["n_points"]})
    return pd.DataFrame(rows)


def run(config: dict, workers: int | None = None, force: bool = False) -> dict[str, pd.DataFrame]:
    start = time.time()
    workers = int(config.get("workers", 1) if workers is None else workers)
    ctx, system, train, monitors, skipped, detectors, runner = _setup(config)
    p1 = config["phase1"]
    sections = {k: config.get(k) for k in CACHE_SECTIONS}
    # OR 統合の組み合わせは集計だけで使うので、途中結果（スコア）の再利用の判定には含めない
    sections["monitoring"] = {k: v for k, v in config["monitoring"].items() if k != "combinations"}
    key = config_hash(sections)
    cache_dir = ctx.cache / f"phase1_{key}"
    cache_dir.mkdir(parents=True, exist_ok=True)
    print(f"[Phase 1] 学習・準備 {time.time() - start:.1f} 秒（手法 {len(monitors)} + 時系列 {len(detectors)}）", flush=True)

    cal = _normal_scores(ctx, runner, monitors, "calibration", int(p1["n_calibration"]), p1, workers, cache_dir)
    ev = _normal_scores(ctx, runner, monitors, "evaluation", int(p1["n_evaluation"]), p1, workers, cache_dir)
    print(f"[Phase 1] 正常データ {len(cal)} + {len(ev)} 本 {time.time() - start:.1f} 秒", flush=True)
    anomaly_file = cache_dir / "anomaly.npz"
    if anomaly_file.exists() and not force:
        stored = np.load(anomaly_file, allow_pickle=True)
        anomaly, perm = stored["anomaly"], stored["perm"]
        sizes, b10, perm_check = (pd.read_parquet(cache_dir / f"{n}.parquet") for n in ("sizes", "b10", "perm_check"))
        examples = dict(np.load(cache_dir / "examples.npz"))
    else:
        anomaly, perm, sizes, b10, perm_check, examples = _anomaly_scores(ctx, runner, monitors, p1)
        np.savez(anomaly_file, anomaly=anomaly, perm=perm)
        for name, frame in (("sizes", sizes), ("b10", b10), ("perm_check", perm_check)):
            frame.to_parquet(cache_dir / f"{name}.parquet")
        np.savez(cache_dir / "examples.npz", **examples)
    print(f"[Phase 1] 異常 {anomaly.shape[0]} パターン × {anomaly.shape[1]} 振幅 × {anomaly.shape[2]} 回 {time.time() - start:.1f} 秒", flush=True)

    table = detector_table(monitors, detectors)
    kappa = {pattern: examples[f"{pattern}_kappa"] for pattern in p1["patterns"]}
    data = {"names": list(table["detector"]), "table": table, "cal": cal, "eval": ev, "anomaly": anomaly, "perm": perm, "kappa": kappa}
    results = summarize(ctx, config, data, monitors)
    sizes["description"] = sizes["pattern"].map(SHAPE_DESCRIPTIONS)
    sizes["label"] = sizes["pattern"].map(SINGLE_WAFER_PATTERNS)
    results["phase1_pattern_sizes"] = sizes
    results["phase1_b10_checks"] = b10
    perm_check["description"] = perm_check["kind"].map(B10_PERMUTATIONS)
    results["phase1_b10_permutation_checks"] = perm_check
    results["phase1_monitor_info"] = monitor_info(monitors, skipped)
    for name, frame in results.items():
        save_table(frame, ctx.out / "metrics" / name)
    _save_samples(ctx, system, train, monitors, examples, data)
    print(f"[Phase 1] 完了 {time.time() - start:.1f} 秒", flush=True)
    return results


def _save_samples(ctx: Context, system, train, monitors, examples, data) -> None:
    """図に使う代表例（座標、正常・異常の計測値、学習データの係数分布など）。"""
    rng = make_rng(ctx.seed, "phase1", "figure_coefficients")
    from ..simulation import sample_stationary_coefficients

    coefficients = sample_stationary_coefficients(system.process, rng, 2000)
    payload = {
        "x_mm": ctx.full_points.x_mm,
        "y_mm": ctx.full_points.y_mm,
        "shot_index": ctx.full_points.shot_index,
        "direction": ctx.full_points.direction,
        "normal_coefficients": coefficients,
        "normal_latent_mean": system.measured_mean(),
        "train_example": train[:3],
        **examples,
    }
    payload["score_names"] = np.array(data["names"])
    # B10 の正常・異常の組（Figure 3）のスコア。base_scores は同じ正常 Wafer（異常を入れる前）のスコア
    patterns = list(ctx.config["phase1"]["patterns"])
    if "B10" in patterns:
        payload["b10_scores"] = data["anomaly"][patterns.index("B10"), :, :200, :]
        payload["b10_base_scores"] = examples["base_scores"][:200]
    payload.pop("base_scores", None)
    payload["eval_scores_head"] = data["eval"][:2000]
    np.savez_compressed(ctx.out / "samples" / "phase1_examples.npz", **payload)
