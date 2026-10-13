"""レポート本文に埋め込む値の定義（どの CSV のどの行・列から作るか）。

fmt："{:.2f}" などの書式、"percent"（小数1桁の %）、"percent2"（小数2桁の %）、"percent0"（整数の %）。
"""
from __future__ import annotations

from .reporting import ValueSpec as V

BLIND = "['B3','B5','B6','B7','B8','B9','B10']"
DET = "phase1_detection"
P = "percent"


def det(key, detector, query, agg="mean", fmt=P, column="detection_rate", table=DET):
    return V(key, table, f"detector == '{detector}' and {query}", column, agg, fmt)


def apc(key, condition, scenario, monitor, order=None, agg="mean", column="detection_rate", fmt=P):
    """APC の1 Wafer の結果（apc_single）。order を省くと全補正次数、振幅は全部をまとめる。"""
    query = f"alignment_condition == '{condition}' and scenario == '{scenario}' and monitor == '{monitor}'"
    if order is not None:
        query += f" and correction_order == {order}"
    return V(key, "apc_single", query, column, agg, fmt)


BASE = "density1_realistic_noise1_orderown"
LEVELS = {
    "full": BASE,
    "25": "density0.25_realistic_noise1_orderown",
    "n3": "density1_realistic_noise3_orderown",
    "n05": "density1_realistic_noise0.5_orderown",
    "o3": "density1_realistic_noise1_order3",
    "o5": "density1_realistic_noise1_order5",
}


def p3(key, level, monitor_or_config, pattern, by="monitor"):
    """Phase 3 の1 Wafer の検出率（全振幅の平均）。pattern = 'all' なら B1〜B10 の平均。"""
    query = f"level == '{LEVELS[level]}' and {by} == '{monitor_or_config}' and sweep == 'single_factor'"
    query += " and pattern != 'normal'" if pattern == "all" else f" and pattern == '{pattern}'"
    return V(key, "phase3_single", query, "detection_rate", "mean", "{:.2f}")


def p3i(key, density, noise, pattern="all"):
    query = f"density == {density} and noise_scale == {noise} and config != 'M3S_XY' and monitor != 'OR[top]'"
    query += " and pattern != 'normal'" if pattern == "all" else f" and pattern == '{pattern}'"
    return V(key, "phase3_interaction", query, "detection_rate", "mean", "{:.2f}")


T2E, MDE, M3C, SPEE, GPRE = "T2_raw_q99|EWMA(λ=0.05)", "MD_d5|EWMA(λ=0.05)", "M3S_XY|CUSUM(k=0.25)", "SPE_raw_q99|EWMA(λ=0.05)", "GPR_rbf_full|EWMA(λ=0.05)"
M3SH, MDH = "M3S_XY|Shewhart", "MD_d5|Shewhart"
NORMAL_FA = "pre_change_false_alarm_rate > 0.1"  # 変化点前の誤報が ARL₀ どおりに出ている検出器


def rank(key, detector, column="mean_rmst_delay", fmt="{:.1f}"):
    return V(key, "phase2_ranking", f"detector == '{detector}'", column, "first", fmt)


def p2(key, detector, pattern=None, amplitude=None, component=None, column="rmst_delay", agg="mean", fmt="{:.1f}"):
    """Phase 2 本評価（phase2_delays）。省いた条件は平均する。"""
    query = f"detector == '{detector}' and pattern != 'no_change'"
    if pattern:
        query += f" and pattern == '{pattern}'"
    if amplitude is not None:
        query += f" and amplitude == {amplitude}"
    if component:
        query += f" and component == '{component}'"
    return V(key, "phase2_delays", query, column, agg, fmt)


def rho(key, detector, rho_value, prewhiten=False, component=None, column="rmst_delay"):
    """時系列相関 ρ の比較（phase2_rho_sweep）。変化なしの系列を除き、パターン・成分・変化量を平均する。"""
    query = f"detector == '{detector}' and rho == {rho_value} and prewhiten == {prewhiten} and pattern != 'no_change'"
    if component:
        query += f" and component == '{component}'"
    return V(key, "phase2_rho_sweep", query, column, "mean", "{:.1f}")


def p3t(key, detector, level, component=None):
    """Phase 3 の経時変化（phase3_temporal）の平均 RMST（変化なしを除く）。"""
    query = f"detector == '{detector}' and level == '{LEVELS[level]}' and pattern != 'no_change'"
    if component:
        query += f" and component == '{component}'"
    return V(key, "phase3_temporal", query, "rmst_delay", "mean", "{:.1f}")


VALUE_SPECS: list[V] = [
    # 第3・4章
    V("b10_max_m3s_diff", "phase1_b10_checks", "", "max_abs_m3s_diff_nm", "max", "{:.1e}"),
    V("b10_capped_8", "phase1_b10_checks", "amplitude == 8", "capped_fraction", "first", "percent0"),
    V("b10_capped_16", "phase1_b10_checks", "amplitude == 16", "capped_fraction", "first", "percent0"),
    V("gpr_shot_sd", "phase1_monitor_info", "monitor == 'GPR_rbf_residual'", "gpr_X_shot_sd", "first", "{:.2f}"),
    V("gpr_mark_sd", "phase1_monitor_info", "monitor == 'GPR_rbf_residual'", "gpr_X_mark_sd", "first", "{:.2f}"),
    V("fpr001_min", "phase1_thresholds", "alpha == 0.01", "fpr", "min", "percent2"),
    V("fpr001_max", "phase1_thresholds", "alpha == 0.01", "fpr", "max", "percent2"),
    V("fpr0001_min", "phase1_thresholds", "alpha == 0.001", "fpr", "min", "percent2"),
    V("fpr0001_max", "phase1_thresholds", "alpha == 0.001", "fpr", "max", "percent2"),
    V("spe99_theoretical_fpr", "phase1_thresholds", "detector == 'SPE_raw_q99' and alpha == 0.001", "fpr_theoretical", "first", P),
    V("t2q99_theoretical_fpr", "phase1_thresholds", "detector == 'T2_raw_q99' and alpha == 0.001", "fpr_theoretical", "first", "percent2"),
    # 第5章 5.1
    V("p1_t2q99_mean", "phase1_representatives", "family == 'M4'", "mean_detection", "first", P),
    V("p1_gpr_mean", "phase1_representatives", "family == 'M6'", "mean_detection", "first", P),
    V("p1_md_mean", "phase1_representatives", "family == 'M3'", "mean_detection", "first", P),
    V("p1_spe_mean", "phase1_representatives", "family == 'M5'", "mean_detection", "first", P),
    V("p1_m3s_mean", "phase1_representatives", "family == 'M1'", "mean_detection", "first", P),
    V("p1_spc_mean", "phase1_representatives", "family == 'M2'", "mean_detection", "first", P),
    V("p1_or_mean", "phase1_representatives", "family == 'OR'", "mean_detection", "first", P),
    det("p1_t2q99_mean_005", "T2_raw_q99", "alpha == 0.05"),
    det("p1_t2q99_mean_0001", "T2_raw_q99", "alpha == 0.001"),
    det("p1_m3s_mean_005", "M3S_XY", "alpha == 0.05"),
    det("p1_m3s_mean_0001", "M3S_XY", "alpha == 0.001"),
    V("p1_md_ewma04", "phase1_ranking", "detector == 'MD_d5|EWMA-scalar(λ=0.4)'", "mean_detection", "first", P),
    V("p1_md_ewma005", "phase1_ranking", "detector == 'MD_d5|EWMA-scalar(λ=0.05)'", "mean_detection", "first", P),
    V("p1_md_mewma04", "phase1_ranking", "detector == 'MD_d5|EWMA(λ=0.4)'", "mean_detection", "first", P),
    V("p1_md_cusum05", "phase1_ranking", "detector == 'MD_d5|CUSUM(k=0.5)'", "mean_detection", "first", P),
    # 5.2
    det("p1_blind_t2q99", "T2_raw_q99", f"alpha == 0.01 and pattern in {BLIND}"),
    det("p1_blind_or", "OR[T2_raw_q95+SPE_raw_q95+GPR_matern52_residual]", f"alpha == 0.01 and pattern in {BLIND}"),
    det("p1_blind_gpr", "GPR_rbf_full", f"alpha == 0.01 and pattern in {BLIND}"),
    det("p1_blind_spe", "SPE_raw_q99", f"alpha == 0.01 and pattern in {BLIND}"),
    det("p1_blind_md", "MD_d5", f"alpha == 0.01 and pattern in {BLIND}"),
    det("p1_blind_m3s", "M3S_XY", f"alpha == 0.01 and pattern in {BLIND}"),
    det("b10_m3s_8", "M3S_XY", "alpha == 0.01 and pattern == 'B10' and amplitude == 8", "first"),
    det("b10_md4_8", "MD_d4", "alpha == 0.01 and pattern == 'B10' and amplitude == 8", "first"),
    det("b10_md5_8", "MD_d5", "alpha == 0.01 and pattern == 'B10' and amplitude == 8", "first"),
    det("b10_spc4_8", "SPC_d4", "alpha == 0.01 and pattern == 'B10' and amplitude == 8", "first"),
    det("b10_t2q99_8", "T2_raw_q99", "alpha == 0.01 and pattern == 'B10' and amplitude == 8", "first"),
    det("b10_spe99_8", "SPE_raw_q99", "alpha == 0.01 and pattern == 'B10' and amplitude == 8", "first"),
    det("b10_gpr_8", "GPR_rbf_full", "alpha == 0.01 and pattern == 'B10' and amplitude == 8", "first"),
    det("perm_shuffle_md", "MD_d5", "alpha == 0.01 and kind == 'shuffle'", "first", table="phase1_b10_permutation"),
    det("perm_mirror_md", "MD_d5", "alpha == 0.01 and kind in ['mirror_x', 'mirror_y']", "mean", table="phase1_b10_permutation"),
    V("perm_rot_max", "phase1_b10_permutation", "alpha == 0.01 and kind == 'rot180'", "detection_rate", "max", P),
    # 5.3
    det("mda_m3s_b1", "M3S_XY", "alpha == 0.01 and pattern == 'B1'", "first", "{:.1f}", "mda50", "phase1_mda"),
    det("mda_m3s_b2", "M3S_XY", "alpha == 0.01 and pattern == 'B2'", "first", "{:.1f}", "mda50", "phase1_mda"),
    det("mda_md_b6", "MD_d5", "alpha == 0.01 and pattern == 'B6'", "first", "{:.1f}", "mda50", "phase1_mda"),
    det("mda_spc_b6", "SPC_d4", "alpha == 0.01 and pattern == 'B6'", "first", "{:.1f}", "mda50", "phase1_mda"),
    det("mda_t2_b9", "T2_raw_q99", "alpha == 0.01 and pattern == 'B9'", "first", "{:.1f}", "mda50", "phase1_mda"),
    det("mda_gpr_b9", "GPR_rbf_full", "alpha == 0.01 and pattern == 'B9'", "first", "{:.1f}", "mda50", "phase1_mda"),
    det("mda_t2_b8", "T2_raw_q99", "alpha == 0.01 and pattern == 'B8'", "first", "{:.1f}", "mda50", "phase1_mda"),
    V("kappa_b3", "phase1_pattern_sizes", "pattern == 'B3' and amplitude == 1", "kappa_mean", "first", "{:.1f}"),
    V("kappa_b9", "phase1_pattern_sizes", "pattern == 'B9' and amplitude == 1", "kappa_mean", "first", "{:.1f}"),
    V("kappa_b7", "phase1_pattern_sizes", "pattern == 'B7' and amplitude == 1", "kappa_mean", "first", "{:.1f}"),

    # 第8章 APC（1 Wafer）
    V("apc_n_align", "apc_single", "alignment_condition == 'standard'", "n_alignment_points", "first", "{:.0f}"),
    V("apc_n_overlay", "apc_single", "alignment_condition == 'standard'", "n_overlay_points", "first", "{:.0f}"),
    V("apc_n_align_sparse", "apc_single", "alignment_condition == 'sparse_noisy'", "n_alignment_points", "first", "{:.0f}"),
    apc("apc_s1_align_m3s", "standard", "S1_linear", "alignment:M3S"),
    apc("apc_s2_align_m3s", "standard", "S2_cubic_radial", "alignment:M3S"),
    apc("apc_s3local_align_spe", "standard", "S3_local", "alignment:SPE"),
    apc("apc_s3local_ovl_spe_o3", "standard", "S3_local", "overlay:SPE", 3),
    apc("apc_s3local_ovl_t2_o3", "standard", "S3_local", "overlay:T2", 3),
    apc("apc_s1_coef_md_o3", "standard", "S1_linear", "coefficient:MD", 3),
    apc("apc_s2_coef_md_o3", "standard", "S2_cubic_radial", "coefficient:MD", 3),
    apc("apc_s3local_coef_md_o1", "standard", "S3_local", "coefficient:MD", 1),
    apc("apc_s3local_coef_md_o5", "standard", "S3_local", "coefficient:MD", 5),
    apc("apc_s1_ovl_m3s_max", "standard", "S1_linear", "overlay:M3S", agg="max"),
    apc("apc_s2_ovl_m3s_o1", "standard", "S2_cubic_radial", "overlay:M3S", 1),
    apc("apc_s2_ovl_m3s_o3", "standard", "S2_cubic_radial", "overlay:M3S", 3),
    apc("apc_normal_rms_o3", "standard", "normal", "overlay:M3S", 3, column="true_overlay_rms_nm", fmt="{:.2f}"),
    apc("apc_normal_rms_o5", "standard", "normal", "overlay:M3S", 5, column="true_overlay_rms_nm", fmt="{:.2f}"),
    apc("apc_sparse_rms_o3", "sparse_noisy", "normal", "overlay:M3S", 3, column="true_overlay_rms_nm", fmt="{:.2f}"),
    apc("apc_sparse_rms_o5", "sparse_noisy", "normal", "overlay:M3S", 5, column="true_overlay_rms_nm", fmt="{:.2f}"),
    apc("apc_sparse_s3local_t2_o3", "sparse_noisy", "S3_local", "overlay:T2", 3),
    apc("apc_sparse_s3local_t2_o5", "sparse_noisy", "S3_local", "overlay:T2", 5),
    apc("apc_sparse_s3local_m3s_o3", "sparse_noisy", "S3_local", "overlay:M3S", 3),
    apc("apc_sparse_s3local_m3s_o5", "sparse_noisy", "S3_local", "overlay:M3S", 5),
    V("apc_flyer_rms16_o5", "apc_single", "alignment_condition == 'standard' and scenario == 'S4_alignment_flyer' and correction_order == 5 and amplitude == 16 and monitor == 'overlay:M3S'", "true_overlay_rms_nm", "first", "{:.2f}"),
    apc("apc_flyer_align_spe", "standard", "S4_alignment_flyer", "alignment:SPE"),

    # 第7章 Phase 3（1 Wafer）
    V("p3_dof_25", "phase3_levels", f"level == '{LEVELS['25']}'", "min_dof_order5", "first", "{:.0f}"),
    V("p3_sens_noise", "phase3_factor_effects", "factor == 'noise_scale'", "sensitivity", "first", "{:.2f}"),
    V("p3_sens_density", "phase3_factor_effects", "factor == 'density'", "sensitivity", "first", "{:.2f}"),
    V("p3_sens_order", "phase3_factor_effects", "factor == 'order'", "sensitivity", "first", "{:.2f}"),
    V("p3_sens_layout", "phase3_factor_effects", "factor == 'layout'", "sensitivity", "first", "{:.2f}"),
    V("p3_range_noise", "phase3_factor_effects", "factor == 'noise_scale'", "range", "first", "{:.2f}"),
    V("p3_range_density", "phase3_factor_effects", "factor == 'density'", "range", "first", "{:.2f}"),
    V("p3_layout_max", "phase3_factor_effects", "factor == 'layout'", "max_cell_range", "first", "{:.2f}"),
    V("p3_layout_min_mean", "phase3_factor_effects", "factor == 'layout'", "min_mean_detection", "first", "{:.2f}"),
    V("p3_layout_max_mean", "phase3_factor_effects", "factor == 'layout'", "max_mean_detection", "first", "{:.2f}"),
    p3("p3_t2_b9_full", "full", "T2_raw_q99", "B9"),
    p3("p3_t2_b9_25", "25", "T2_raw_q99", "B9"),
    p3("p3_t2_b9_n3", "n3", "T2_raw_q99", "B9"),
    p3("p3_t2_b9_n05", "n05", "T2_raw_q99", "B9"),
    p3("p3_t2_b8_full", "full", "T2_raw_q99", "B8"),
    p3("p3_t2_b8_25", "25", "T2_raw_q99", "B8"),
    p3("p3_t2_b8_n3", "n3", "T2_raw_q99", "B8"),
    p3("p3_t2_b7_full", "full", "T2_raw_q99", "B7"),
    p3("p3_t2_b7_25", "25", "T2_raw_q99", "B7"),
    p3("p3_t2_b7_n3", "n3", "T2_raw_q99", "B7"),
    p3("p3_t2_b3_full", "full", "T2_raw_q99", "B3"),
    p3("p3_t2_b3_25", "25", "T2_raw_q99", "B3"),
    p3("p3_md_all_full", "full", "MD_d5", "all"),
    p3("p3_md_all_25", "25", "MD_d5", "all"),
    p3("p3_gpr_b9_n05", "n05", "GPR_rbf_full", "B9"),
    V("p3_k_t2_n1", "phase3_levels", f"level == '{LEVELS['full']}'", "pca_components_T2_raw_q99", "first", "{:.0f}"),
    V("p3_k_t2_n05", "phase3_levels", f"level == '{LEVELS['n05']}'", "pca_components_T2_raw_q99", "first", "{:.0f}"),
    p3("p3_md_b5_o3", "o3", "MD_d5", "B5", by="config"),
    p3("p3_md_b5_o5", "o5", "MD_d5", "B5", by="config"),
    p3("p3_md_b10_o3", "o3", "MD_d5", "B10", by="config"),
    p3("p3_md_b10_o5", "o5", "MD_d5", "B10", by="config"),
    p3("p3_md_b4_o3", "o3", "MD_d5", "B4", by="config"),
    p3("p3_md_b4_o5", "o5", "MD_d5", "B4", by="config"),
    p3i("p3_int_full_n1", 1.0, 1.0),
    p3i("p3_int_25_n3", 0.25, 3.0),
    p3i("p3_int_b9_full_n1", 1.0, 1.0, "B9"),
    p3i("p3_int_b9_25_n3", 0.25, 3.0, "B9"),

    # 第6章 Phase 2
    V("p2_arl_min", "phase2_arl0", "", "arl", "min", "{:.0f}"),
    V("p2_arl_max", "phase2_arl0", "", "arl", "max", "{:.0f}"),
    V("p2_null_min", "phase2_ranking", NORMAL_FA, "null_rmst_delay", "min", "{:.0f}"),
    V("p2_null_max", "phase2_ranking", NORMAL_FA, "null_rmst_delay", "max", "{:.0f}"),
    V("p2_prefa_min", "phase2_ranking", NORMAL_FA, "pre_change_false_alarm_rate", "min", "percent0"),
    V("p2_prefa_max", "phase2_ranking", NORMAL_FA, "pre_change_false_alarm_rate", "max", "percent0"),
    rank("p2_prefa_t2cusum", "T2_raw_q99|CUSUM(k=1)", "pre_change_false_alarm_rate", "percent"),
    rank("p2_det_specusum", "SPE_raw_q99|CUSUM(k=1)", "mean_detection_rate", "percent"),
    rank("p2_rmst_t2ewma", T2E),
    rank("p2_rmst_mdewma", MDE),
    rank("p2_rmst_m3scusum", M3C),
    rank("p2_rmst_speewma", SPEE),
    rank("p2_rmst_gprewma", GPRE),
    rank("p2_rmst_m3sshew", M3SH),
    rank("p2_rmst_spcbest", "SPC_d4|CUSUM(k=1)"),
    p2("p2_a1_1_mdewma", MDE, "A1", 1.0),
    p2("p2_a1_1_t2ewma", T2E, "A1", 1.0),
    p2("p2_a1_1_m3s", M3SH, "A1", 1.0),
    p2("p2_a1_3_mdewma", MDE, "A1", 3.0),
    p2("p2_a1_3_t2ewma", T2E, "A1", 3.0),
    p2("p2_a1_3_m3s", M3SH, "A1", 3.0),
    p2("p2_a1_local_1_speewma", SPEE, "A1", 1.0, "local", "median_delay", "first", "{:.0f}"),
    p2("p2_a1_local_1_m3s", M3SH, "A1", 1.0, "local", "median_delay", "first", "{:.0f}"),
    p2("p2_a2_3_t2ewma", T2E, "A2", 3.0),
    p2("p2_a2_3_mdewma", MDE, "A2", 3.0),
    p2("p2_a2_3_m3s", M3SH, "A2", 3.0),
    p2("p2_a3_3_t2ewma", T2E, "A3", 3.0),
    p2("p2_a3_3_mdewma", MDE, "A3", 3.0),
    p2("p2_a3_3_m3s", M3SH, "A3", 3.0),
    p2("p2_a4_3_mdewma", MDE, "A4", 3.0),
    p2("p2_a4_3_mdshew", MDH, "A4", 3.0),
    p2("p2_a4_3_t2ewma", T2E, "A4", 3.0),
    p2("p2_a4_3_m3scusum", M3C, "A4", 3.0),
    p2("p2_a4_3_speewma", SPEE, "A4", 3.0),
    p2("p2_local_speewma", SPEE, component="local"),
    p2("p2_radial_m3scusum", M3C, component="radial"),
    p2("p2_radial_t2ewma", T2E, component="radial"),
    p2("p2_low_mdewma", MDE, component="low"),
    p2("p2_high_mdewma", MDE, component="high"),
    p2("p2_detonly_t2ewma", T2E, column="mean_delay_detected"),
    p2("p2_detonly_m3s", M3SH, column="mean_delay_detected"),

    # 第8章 APC（経時変化）
    V("apc_t_null_min", "apc_temporal", "pattern == 'no_change'", "rmst_delay", "min", "{:.0f}"),
    V("apc_t_null_max", "apc_temporal", "pattern == 'no_change'", "rmst_delay", "max", "{:.0f}"),
    V("apc_t_low_ovl_t2", "apc_temporal", "detector == 'overlay:T2|EWMA(λ=0.1)' and component == 'low'", "rmst_delay", "mean", "{:.0f}"),
    V("apc_t_low_align_t2", "apc_temporal", "detector == 'alignment:T2|EWMA(λ=0.1)' and component == 'low'", "rmst_delay", "mean", "{:.0f}"),
    V("apc_t_low_coef_md", "apc_temporal", "detector == 'coefficient:MD|EWMA(λ=0.1)' and component == 'low'", "rmst_delay", "mean", "{:.0f}"),
    V("apc_t_local_ovl_spe", "apc_temporal", "detector == 'overlay:SPE|EWMA(λ=0.1)' and component == 'local'", "rmst_delay", "mean", "{:.0f}"),
    V("apc_t_local_coef_md", "apc_temporal", "detector == 'coefficient:MD|EWMA(λ=0.1)' and component == 'local'", "rmst_delay", "mean", "{:.0f}"),

    # 第9・10章
    V("b8_rms4", "phase1_pattern_sizes", "pattern == 'B8' and amplitude == 4", "rms_nm", "first", "{:.2f}"),
    V("p3_k_t2_n3", "phase3_levels", f"level == '{LEVELS['n3']}'", "pca_components_T2_raw_q99", "first", "{:.0f}"),

    # 第6.7節 ρ
    rho("rho_t2e_0", T2E, 0.0),
    rho("rho_t2e_95", T2E, 0.95),
    rho("rho_mde_0", MDE, 0.0),
    rho("rho_mde_95", MDE, 0.95),
    rho("rho_t2s_0", "T2_raw_q99|Shewhart", 0.0),
    rho("rho_t2s_95", "T2_raw_q99|Shewhart", 0.95),
    rho("rho_m3ss_0", M3SH, 0.0),
    rho("rho_m3ss_95", M3SH, 0.95),
    rho("rho_spee_95", SPEE, 0.95),
    rho("rho_spes_95", "SPE_raw_q99|Shewhart", 0.95),
    rho("rho_t2e_95_pw", T2E, 0.95, True),
    rho("rho_mde_95_pw", MDE, 0.95, True),
    rho("rho_t2s_95_pw", "T2_raw_q99|Shewhart", 0.95, True),
    rho("rho_mdc_95", "MD_d5|CUSUM(k=1)", 0.95),
    rho("rho_mdc_95_pw", "MD_d5|CUSUM(k=1)", 0.95, True),
    V("rho_phi_95", "phase2_rho_sweep", "rho == 0.95 and prewhiten == True", "ar1_phi", "first", "{:.2f}"),

    # 第7.6節 Phase 3 の経時変化
    p3t("p3t_t2_full", T2E, "full"),
    p3t("p3t_t2_25", T2E, "25"),
    p3t("p3t_t2_n3", T2E, "n3"),
    p3t("p3t_t2_n05", T2E, "n05"),
    p3t("p3t_spe_local_full", SPEE, "full", "local"),
    p3t("p3t_spe_local_n3", SPEE, "n3", "local"),

    p2("p2_a4_1_mdewma", MDE, "A4", 1.0),
    rank("p2_null_mdewma", MDE, "null_rmst_delay"),

    p3("p3_gpr_b4_full", "full", "GPR_rbf_full", "B4"),
    p3("p3_gpr_b4_25", "25", "GPR_rbf_full", "B4"),
    p3("p3_m3s_all_full", "full", "M3S_XY", "all"),
    p3("p3_m3s_all_n3", "n3", "M3S_XY", "all"),
    p3("p3_or_all_n05", "n05", "OR[top]", "all"),
    p3("p3_or_all_full", "full", "OR[top]", "all"),

    V("p1_or3_mean", "phase1_ranking", "detector == 'OR[T2_raw_q95+SPE_raw_q95+GPR_matern52_residual]'", "mean_detection", "first", P),
    det("p1_blind_or5", "OR[M3S_XY+MD_d4+T2_raw_q99+SPE_raw_q99+GPR_rbf_full]", f"alpha == 0.01 and pattern in {BLIND}"),
]
