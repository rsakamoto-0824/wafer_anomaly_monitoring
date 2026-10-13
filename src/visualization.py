"""図の作成（Figure 1〜10 と付録の図）。PNG と PDF の両方で results/figures に保存する。

色の約束（色は手法の系統に固定。並び順や絞り込みで塗り替えない）
- 系統 M2〜M8・OR は参照パレットのカテゴリ色を固定順で使い、ベースラインの M3S（M1）は中立の濃い灰色。
- 量（検出率など）は青の単色グラデーション、正負のある量（X・Y の変位）は青↔赤＋灰色の中点。
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Circle  # noqa: E402

from .anomaly_generator import SINGLE_WAFER_PATTERNS, TEMPORAL_COMPONENTS  # noqa: E402
from .experiments.common import FAMILY_LABELS, build_context  # noqa: E402
from .temporal_process import TEMPORAL_PATTERNS  # noqa: E402
from .zernike import fringe_index  # noqa: E402

FONT_FAMILY = ["Hiragino Sans", "BIZ UDGothic", "Yu Gothic", "Meiryo", "Noto Sans CJK JP", "DejaVu Sans"]
DPI = 200
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SURFACE = "#fcfcfb"
FAMILY_COLORS = {
    "M1": "#52514e",
    "M2": "#2a78d6",
    "M3": "#eb6834",
    "M4": "#1baf7a",
    "M5": "#eda100",
    "M6": "#e87ba4",
    "M7": "#008300",
    "M8": "#4a3aa7",
    "OR": "#e34948",
    "Oracle": "#898781",
}
SCHEME_COLORS = {"shewhart": "#2a78d6", "ewma": "#008300", "ewma-scalar": "#008300", "cusum": "#4a3aa7"}
AXIS_COLORS = {"X": "#2a78d6", "Y": "#eb6834"}
SEQUENTIAL = LinearSegmentedColormap.from_list("blue_seq", ["#f3f8fe", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"])
DIVERGING = LinearSegmentedColormap.from_list("blue_red", ["#104281", "#3987e5", "#f0efec", "#e66767", "#9e2a2a"])
FAMILY_ORDER = ("M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8")
SHOT_PITCH_MM = (26.0, 33.0)  # 矢印を Shot ごとにまとめるときの格子（configs の shot_size_mm と同じ）


def setup_style() -> None:
    installed = {font.name for font in font_manager.fontManager.ttflist}
    plt.rcParams.update(
        {
            "font.family": [name for name in FONT_FAMILY if name in installed] or ["DejaVu Sans"],
            "font.size": 8.5,
            "axes.titlesize": 9.5,
            "axes.labelsize": 8.5,
            "axes.edgecolor": AXIS,
            "axes.labelcolor": INK,
            "axes.titlecolor": INK,
            "axes.grid": True,
            "grid.color": GRID,
            "grid.linewidth": 0.6,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "xtick.color": INK_SECONDARY,
            "ytick.color": INK_SECONDARY,
            "legend.frameon": False,
            "legend.fontsize": 7.5,
            "figure.facecolor": "white",
            "savefig.facecolor": "white",
            "axes.unicode_minus": False,
            "pdf.fonttype": 42,
            "lines.linewidth": 1.6,
        }
    )


def save(fig, folder: Path, name: str) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for suffix in (".png", ".pdf"):
        path = folder / f"{name}{suffix}"
        fig.savefig(path, dpi=DPI, bbox_inches="tight")
        paths.append(path)
    plt.close(fig)
    return paths


# ---------------------------------------------------------------------- 共通の描き方
def wafer_frame(ax, radius=150.0, title=None) -> None:
    ax.add_patch(Circle((0, 0), radius, fill=False, color=AXIS, linewidth=0.8))
    ax.set_xlim(-radius * 1.04, radius * 1.04)
    ax.set_ylim(-radius * 1.04, radius * 1.04)
    ax.set_aspect("equal")
    ax.grid(False)
    ax.set_xticks([-150, 0, 150])
    ax.set_yticks([-150, 0, 150])
    ax.tick_params(labelsize=6.5)
    if title:
        ax.set_title(title, fontsize=8.5)


def scalar_map(ax, x, y, values, limit, title=None, size=9):
    norm = TwoSlopeNorm(vcenter=0.0, vmin=-limit, vmax=limit)
    artist = ax.scatter(x, y, c=values, cmap=DIVERGING, norm=norm, s=size, marker="s", linewidths=0)
    wafer_frame(ax, title=title)
    return artist


def vector_map(ax, x, y, dx, dy, scale, title=None, color=INK, key_nm=None, per_shot=True):
    """XY 変位の矢印。per_shot なら Shot ごとに平均して1本にする（Shot は 26 × 33 mm の格子で判定）。
    矢印の長さは scale [mm/nm] 倍で描く（同じ行の図では同じ scale を使う）。"""
    if per_shot:
        col = np.round(np.asarray(x) / SHOT_PITCH_MM[0]).astype(int)
        row = np.round(np.asarray(y) / SHOT_PITCH_MM[1]).astype(int)
        keys = col * 1000 + row
        _, inverse = np.unique(keys, return_inverse=True)
        count = np.bincount(inverse)
        x, y, dx, dy = (np.bincount(inverse, weights=v) / count for v in (x, y, dx, dy))
    ax.quiver(x, y, dx * scale, dy * scale, angles="xy", scale_units="xy", scale=1.0, color=color, width=0.0065, headwidth=3.2, headlength=3.6, headaxislength=3.2, pivot="middle")
    wafer_frame(ax, title=title)
    if key_nm:
        ax.quiver([-135], [-145], [key_nm * scale], [0], angles="xy", scale_units="xy", scale=1.0, color=INK_SECONDARY, width=0.0065, headwidth=3.2, headlength=3.6, headaxislength=3.2)
        ax.text(-140, -136, f"{key_nm:g} nm", fontsize=6.5, color=INK_SECONDARY)


def split_xy(values):
    n = len(values) // 2
    return values[:n], values[n:]


def nice_key(max_nm: float) -> float:
    for candidate in (0.5, 1, 2, 5, 10, 20, 50, 100):
        if candidate >= max_nm * 0.4:
            return candidate
    return 100.0


# ---------------------------------------------------------------------- Figure 1
def figure1_normal(ctx, samples, folder):
    x, y = samples["x_mm"], samples["y_mm"]
    latent = samples["base_latent"][0]
    lx, ly = split_xy(latent)
    fig, axes = plt.subplots(1, 4, figsize=(15, 3.8), gridspec_kw={"width_ratios": [1, 1, 1, 1.9]})
    magnitude = np.hypot(lx, ly)
    scale = 22.0 / np.percentile(magnitude, 95)
    vector_map(axes[0], x, y, lx, ly, scale, "(a) XY 変位ベクトル場（潜在値）", key_nm=nice_key(np.percentile(magnitude, 95)))
    limit = np.percentile(np.abs(latent), 98)
    scalar_map(axes[1], x, y, lx, limit, "(b) X 成分 [nm]")
    artist = scalar_map(axes[2], x, y, ly, limit, "(c) Y 成分 [nm]")
    fig.colorbar(artist, ax=axes[1:3], shrink=0.75, label="nm")
    coefficients = samples["normal_coefficients"]
    k = coefficients.shape[1] // 2
    modes = ctx.process.modes
    order = np.argsort([fringe_index(*m) for m in modes])
    labels = [f"Z{fringe_index(*modes[i])}" for i in order]
    positions = np.arange(k)
    ax = axes[3]
    for offset, (axis, block) in zip((-0.18, 0.18), (("X", slice(0, k)), ("Y", slice(k, 2 * k)))):
        data = coefficients[:, block][:, order]
        mean, sd = data.mean(axis=0), data.std(axis=0)
        ax.errorbar(positions + offset, mean, yerr=sd, fmt="o", ms=3, color=AXIS_COLORS[axis], elinewidth=1, capsize=0, label=f"{axis} 係数（平均 ± 標準偏差）")
    ax.set_xticks(positions[::2], labels[::2], rotation=90, fontsize=6)
    ax.set_ylabel("係数 [nm]（円板上の RMS）")
    ax.set_title("(d) Zernike 係数の分布（Fringe 番号順、n ≤ 7、2,000 枚）")
    ax.axhline(0, color=AXIS, linewidth=0.8)
    ax.legend(loc="upper right")
    return save(fig, folder, "figure01_normal_wafer")


# ---------------------------------------------------------------------- Figure 2
def figure2_anomalies(ctx, samples, folder, amplitude=4.0):
    x, y = samples["x_mm"], samples["y_mm"]
    base = samples["base_latent"][0]
    patterns = [p for p in SINGLE_WAFER_PATTERNS if f"{p}_a{amplitude:g}_displacement" in samples]
    paths = []
    for page, group in enumerate((patterns[:5], patterns[5:])):
        if not group:
            continue
        fig, axes = plt.subplots(len(group), 3, figsize=(9.5, 3.0 * len(group)))
        axes = np.atleast_2d(axes)
        for row, pattern in enumerate(group):
            delta = samples[f"{pattern}_a{amplitude:g}_displacement"][0]
            anomalous = base + delta
            bx, by = split_xy(base)
            ax_, ay_ = split_xy(anomalous)
            dx, dy = split_xy(delta)
            scale = 16.0 / np.percentile(np.hypot(bx, by), 95)
            key = nice_key(np.percentile(np.hypot(bx, by), 95))
            vector_map(axes[row, 0], x, y, bx, by, scale, f"{pattern} 正常の面内傾向", key_nm=key)
            vector_map(axes[row, 1], x, y, ax_, ay_, scale, f"{pattern} 異常（振幅 {amplitude:g}σ_dir）", key_nm=key)
            d_scale = 16.0 / max(np.max(np.hypot(dx, dy)), 1e-9)
            vector_map(axes[row, 2], x, y, dx, dy, d_scale, f"差分：{SINGLE_WAFER_PATTERNS[pattern]}", color=FAMILY_COLORS["OR"], key_nm=nice_key(np.max(np.hypot(dx, dy))))
        fig.suptitle("Figure 2 異常 Wafer の例（左・中：同じ矢印の縮尺、右：差分だけ拡大。矢印は Shot ごとの平均）", fontsize=10)
        fig.tight_layout(rect=(0, 0, 1, 0.975))
        paths += save(fig, folder, f"figure02_anomaly_examples_{page + 1}")
    return paths


# ---------------------------------------------------------------------- Figure 3
def figure3_b10(ctx, samples, metrics, folder, amplitude_index=3):
    names = list(samples["score_names"])
    base_scores = samples["b10_base_scores"]
    scores = samples["b10_scores"][amplitude_index]
    amplitudes = ctx.config["phase1"]["amplitudes"]
    x, y = samples["x_mm"], samples["y_mm"]
    normal = samples["base_measured"][0]
    anomalous = samples[f"B10_a{amplitudes[amplitude_index]:g}_measured"][0]
    fig = plt.figure(figsize=(14, 6.8))
    grid = fig.add_gridspec(2, 4)
    limit = np.percentile(np.abs(np.concatenate([normal, anomalous])), 98)
    for col, (values, title) in enumerate(((normal, "(a) 正常 Wafer（計測値）X"), (anomalous, f"(b) B10 異常（{amplitudes[amplitude_index]:g}σ_dir）X"))):
        ax = fig.add_subplot(grid[0, col])
        artist = scalar_map(ax, x, y, split_xy(values)[0], limit, title)
    fig.colorbar(artist, ax=ax, fraction=0.046, pad=0.03, label="nm")
    ax = fig.add_subplot(grid[0, 2:])
    m3s = [np.abs(v.mean()) + 3 * v.std(ddof=1) for v in (*split_xy(normal), *split_xy(anomalous))]
    largest_gap = max(abs(m3s[0] - m3s[2]), abs(m3s[1] - m3s[3]))
    bars = ax.bar([0, 1, 3, 4], m3s, color=[AXIS_COLORS["X"], AXIS_COLORS["Y"]] * 2, width=0.8)
    ax.set_xticks([0, 1, 3, 4], ["正常 X", "正常 Y", "B10 X", "B10 Y"])
    for bar, value in zip(bars, m3s):
        ax.text(bar.get_x() + bar.get_width() / 2, value, f"{value:.4f}", ha="center", va="bottom", fontsize=7, color=INK)
    ax.set_ylabel("M3S [nm]")
    ax.set_title(f"(c) M3S は X・Y とも同じ（この Wafer の差の最大 {largest_gap:.1e} nm）")
    panels = [("M3S_XY", "(d) M3S（XY 統合スコア）"), ("T2_raw_q99", "(e) PCA T²（計測値、99%）"), ("MD_d5", "(f) Mahalanobis 距離（5次係数）"), ("SPC_d4", "(g) 係数 SPC（4次、max|z|）")]
    thresholds = metrics["phase1_thresholds"]
    for col, (name, title) in enumerate(panels):
        if name not in names:
            continue
        j = names.index(name)
        ax = fig.add_subplot(grid[1, col])
        ax.scatter(base_scores[:, j], scores[:, j], s=8, color=FAMILY_COLORS[_family(name)], alpha=0.7, linewidths=0)
        low = min(base_scores[:, j].min(), scores[:, j].min())
        high = max(base_scores[:, j].max(), scores[:, j].max())
        ax.plot([low, high], [low, high], color=AXIS, linewidth=1)
        limit_value = thresholds[(thresholds["detector"] == name) & (thresholds["alpha"] == 0.01)]["threshold"]
        if len(limit_value):
            ax.axhline(limit_value.iloc[0], color=FAMILY_COLORS["OR"], linewidth=1)
            ax.axvline(limit_value.iloc[0], color=FAMILY_COLORS["OR"], linewidth=1)
        ax.set_xlabel("同じ Wafer の正常時のスコア")
        ax.set_ylabel("B10 異常後のスコア")
        ax.set_title(title, fontsize=8.5)
    fig.suptitle("Figure 3 M3S が同一の異常（B10）：赤線は誤報率1%の管理限界、灰線は y = x", fontsize=10)
    fig.tight_layout()
    return save(fig, folder, "figure03_b10_same_m3s")


def short_label(name: str) -> str:
    """図の軸に入る短い名前（OR 統合は要素の系統名だけ、時系列は改行して方式を下に）。"""
    if name.startswith("OR["):
        return "OR\n" + "+".join(part.split("_")[0] for part in name[3:-1].split("+"))
    name = name.replace("GPR_matern52_residual", "GPR_m52_res").replace("GPR_rbf_residual", "GPR_rbf_res")
    return name.replace("|", "\n").replace("-scalar", "")


def _family(name: str) -> str:
    if name.startswith("OR["):
        return "OR"
    if "|EWMA" in name:
        return "M7"
    if "|CUSUM" in name:
        return "M8"
    for prefix, family in (("M3S", "M1"), ("SPC", "M2"), ("MD", "M3"), ("T2", "M4"), ("SPE", "M5"), ("GPR", "M6"), ("Oracle", "Oracle")):
        if name.startswith(prefix):
            return family
    return "Oracle"


# ---------------------------------------------------------------------- Figure 4・5
def representatives(metrics) -> pd.DataFrame:
    reps = metrics["phase1_representatives"]
    return reps[reps["family"].isin(FAMILY_ORDER)].set_index("family").reindex(FAMILY_ORDER).dropna(subset=["representative"])


def figure4_detection_curves(metrics, folder, alpha=0.01):
    detection = metrics["phase1_detection"]
    detection = detection[detection["alpha"] == alpha]
    reps = representatives(metrics)
    patterns = list(SINGLE_WAFER_PATTERNS)
    fig, axes = plt.subplots(2, 5, figsize=(15, 6.4), sharex=True, sharey=True)
    for ax, pattern in zip(axes.ravel(), patterns):
        for family, row in reps.iterrows():
            data = detection[(detection["detector"] == row["representative"]) & (detection["pattern"] == pattern)].sort_values("amplitude")
            ax.plot(data["amplitude"], data["detection_rate"], marker="o", ms=3.5, color=FAMILY_COLORS[family], linewidth=1.6 if family != "M1" else 2.2)
        oracle = detection[(detection["detector"] == "Oracle_projection") & (detection["pattern"] == pattern)].sort_values("amplitude")
        ax.plot(oracle["amplitude"], oracle["detection_rate"], color=FAMILY_COLORS["Oracle"], linestyle=(0, (3, 2)), linewidth=1.2)
        ax.axhline(alpha, color=AXIS, linewidth=0.8)
        ax.set_xscale("log", base=2)
        ax.set_xticks([1, 2, 4, 8, 16], ["1", "2", "4", "8", "16"])
        ax.set_ylim(-0.02, 1.02)
        ax.set_title(f"{pattern} {SINGLE_WAFER_PATTERNS[pattern]}", fontsize=8.2)
    for ax in axes[1]:
        ax.set_xlabel("異常振幅 [σ_dir]")
    for ax in axes[:, 0]:
        ax.set_ylabel("検出率（誤報率 1%）")
    handles = [Line2D([], [], color=FAMILY_COLORS[f], marker="o", ms=3.5, label=f"{FAMILY_LABELS[f]}（{row['representative']}）") for f, row in reps.iterrows()]
    handles.append(Line2D([], [], color=FAMILY_COLORS["Oracle"], linestyle=(0, (3, 2)), label="方向既知の射影管理図（理論値、参考）"))
    fig.legend(handles=handles, loc="lower center", ncol=3, bbox_to_anchor=(0.5, -0.07))
    fig.suptitle("Figure 4 異常振幅と検出率（1 Wafer の異常検知、各点 1,000 回、M7・M8 は正常 Wafer の流れの中の単発異常）", fontsize=10)
    fig.tight_layout()
    return save(fig, folder, "figure04_detection_curves")


def figure5_heatmap(metrics, folder, alpha=0.01, amplitude=4.0, name="figure05_pattern_heatmap", average=False):
    detection = metrics["phase1_detection"]
    detection = detection[detection["alpha"] == alpha]
    reps = representatives(metrics)
    columns = list(reps["representative"])
    best_or = metrics["phase1_representatives"].query("family == 'OR'")["representative"]
    columns += list(best_or)
    data = detection[detection["detector"].isin(columns)]
    data = data.groupby(["pattern", "detector"])["detection_rate"].mean() if average else data[data["amplitude"] == amplitude].set_index(["pattern", "detector"])["detection_rate"]
    matrix = data.unstack().reindex(index=list(SINGLE_WAFER_PATTERNS), columns=columns)
    fig, ax = plt.subplots(figsize=(11.5, 5.4))
    image = ax.imshow(matrix.to_numpy(), cmap=SEQUENTIAL, vmin=0, vmax=1, aspect="auto")
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            value = matrix.iat[i, j]
            ax.text(j, i, f"{value:.2f}", ha="center", va="center", fontsize=7.5, color="white" if value > 0.55 else INK)
    labels = [f"{FAMILY_LABELS.get(_family(c), c)}\n{short_label(c)}" for c in columns]
    ax.set_xticks(range(len(columns)), labels, fontsize=6.8)
    ax.set_yticks(range(len(matrix)), [f"{p} {SINGLE_WAFER_PATTERNS[p]}" for p in matrix.index], fontsize=7.5)
    ax.grid(False)
    fig.colorbar(image, ax=ax, shrink=0.8, label="検出率")
    what = "全振幅（1〜16σ_dir）の平均" if average else f"振幅 {amplitude:g}σ_dir"
    ax.set_title(f"Figure 5 異常パターン別の検出率（{what}、誤報率 {alpha:.0%}）")
    fig.tight_layout()
    return save(fig, folder, name)


# ---------------------------------------------------------------------- Figure 6・7
def figure6_temporal_example(folder, samples):
    names = list(samples["names"])
    stats = samples["statistics"]
    thresholds = samples["thresholds"]
    change = samples["true_change_sigma"]
    t = np.arange(1, len(change) + 1)
    # 仕様の Figure 6 の項目：M3S・係数 SPC・PCA T²・PCA SPE（各 Wafer の判定）と、EWMA・CUSUM の代表
    preferred = [("M3S_XY", "Shewhart"), ("SPC_d", "Shewhart"), ("T2_raw", "Shewhart"), ("SPE_raw", "Shewhart"),
                 ("T2_raw", "EWMA"), ("MD_d", "EWMA"), ("M3S_XY", "CUSUM"), ("SPC_d", "CUSUM")]
    wanted = []
    for base, scheme in preferred:
        match = [n for n in names if n.startswith(base) and f"|{scheme}" in n]
        if match:
            wanted.append(match[0])
    rows = 1 + len(wanted)
    fig, axes = plt.subplots(rows, 1, figsize=(10, 1.25 * rows + 0.6), sharex=True)
    axes[0].plot(t, change, color=FAMILY_COLORS["OR"])
    axes[0].set_ylabel("変化量\n[σ_dir]", fontsize=7)
    axes[0].set_title(f"Figure 6 経時変化の検出例：{TEMPORAL_PATTERNS[str(samples['pattern'])]}・{TEMPORAL_COMPONENTS[str(samples['component'])]}・{float(samples['amplitude']):g}σ_dir（1 系列）", fontsize=9)
    onset = int(np.argmax(change != 0)) + 1
    for ax, name in zip(axes[1:], wanted):
        j = names.index(name)
        series = stats[:, j]
        color = SCHEME_COLORS["shewhart"] if "Shewhart" in name else SCHEME_COLORS["ewma"] if "EWMA" in name else SCHEME_COLORS["cusum"]
        ax.plot(t, series, color=color, linewidth=1.0)
        ax.axhline(thresholds[j], color=FAMILY_COLORS["OR"], linewidth=0.9)
        alarms = np.flatnonzero((series > thresholds[j]) & (t >= onset))
        if len(alarms):
            ax.axvline(t[alarms[0]], color=INK_MUTED, linewidth=0.8)
            ax.text(t[alarms[0]] + 2, ax.get_ylim()[1] * 0.85 if ax.get_ylim()[1] > 0 else 0, f"検出 {t[alarms[0]] - onset + 1} 枚目", fontsize=6.5, color=INK_SECONDARY)
        ax.set_ylabel(name.replace("|", "\n"), fontsize=6, rotation=0, ha="right", va="center")
        ax.tick_params(labelsize=6)
    for ax in axes:
        ax.axvline(onset, color=AXIS, linewidth=0.8)
    axes[-1].set_xlabel("Wafer（時系列順、101 枚目から変化。赤線＝ARL₀ = 370 の管理限界、灰線＝変化後の最初の警報。EWMA・SPE は 0 から立ち上がる）")
    fig.tight_layout()
    return save(fig, folder, "figure06_temporal_example")


def best_per_base(ranking: pd.DataFrame) -> list[str]:
    """土台の手法ごとに平均 RMST が最小の方式と、ベースラインの M3S（Shewhart）。"""
    best = ranking.sort_values("mean_rmst_delay").drop_duplicates("base")["detector"].tolist()
    if "M3S_XY|Shewhart" not in best:
        best.append("M3S_XY|Shewhart")
    return best


def figure7_delays(metrics, folder):
    delays = metrics["phase2_delays"]
    ranking = metrics["phase2_ranking"]
    detectors = best_per_base(ranking)
    null = delays[delays["pattern"] == "no_change"]
    null_rmst = null["rmst_delay"].mean()
    null_detection = null["detection_rate"].mean()
    patterns = list(TEMPORAL_PATTERNS)
    fig, axes = plt.subplots(2, len(patterns), figsize=(15, 6.6), sharex=True, sharey="row")
    for col, pattern in enumerate(patterns):
        data = delays[delays["pattern"] == pattern].groupby(["detector", "amplitude"], as_index=False)[["rmst_delay", "detection_rate"]].mean()
        for name in detectors:
            subset = data[data["detector"] == name].sort_values("amplitude")
            style = _detector_style(name)
            axes[0, col].plot(subset["amplitude"], subset["rmst_delay"], **style)
            axes[1, col].plot(subset["amplitude"], 1 - subset["detection_rate"], **style)
        axes[0, col].axhline(null_rmst, color=INK_MUTED, linewidth=0.9)
        axes[1, col].axhline(1 - null_detection, color=INK_MUTED, linewidth=0.9)
        axes[0, col].set_title(f"{pattern} {TEMPORAL_PATTERNS[pattern]}（6成分の平均）", fontsize=8.5)
        axes[1, col].set_xlabel("変化量 [σ_dir]")
        axes[0, col].set_yscale("log")
    axes[0, 0].text(0.3, null_rmst * 1.05, "変化なし（誤報だけ）", fontsize=6.5, color=INK_SECONDARY)
    axes[0, 0].set_ylabel("制限付き平均遅延 RMST [枚]\n（未検出は 200 枚として数える）")
    axes[1, 0].set_ylabel("未検出率（変化後 200 枚以内）")
    handles = [Line2D([], [], label=name, **_detector_style(name)) for name in detectors]
    handles.append(Line2D([], [], color=INK_MUTED, label="変化なしの系列（誤報だけで検出になる基準）"))
    fig.legend(handles=handles, loc="lower center", ncol=4, bbox_to_anchor=(0.5, -0.12), fontsize=7)
    fig.suptitle("Figure 7 変化量と検出遅延・未検出率（ARL₀ = 370、変化点前に誤報のない系列の条件付き遅延、各条件 1,000 系列）", fontsize=10)
    fig.tight_layout()
    return save(fig, folder, "figure07_detection_delay")


def _detector_style(name: str) -> dict:
    base = name.split("|")[0]
    family = _family(base)
    scheme = "shewhart" if "Shewhart" in name else "ewma" if "EWMA" in name else "cusum"
    linestyle = {"shewhart": "-", "ewma": (0, (4, 1.5)), "cusum": (0, (1, 1.2))}[scheme]
    marker = {"shewhart": "o", "ewma": "s", "cusum": "^"}[scheme]
    return {"color": FAMILY_COLORS[family], "linestyle": linestyle, "marker": marker, "ms": 3.5, "linewidth": 1.5}


# ---------------------------------------------------------------------- Figure 8・9（Phase 3）
PHASE3_PANELS = ("all", "B3", "B7", "B8", "B9", "B10")


def _phase3_panels(frame, x_key, x_values, x_labels, title, folder, name, xlabel):
    """計測条件（x）ごとの検出率を、全パターンの平均と影響の大きいパターン別の小さな図に分けて描く。"""
    fig, axes = plt.subplots(2, 3, figsize=(13.5, 7.2), sharey=True)
    anomalies = frame[frame["pattern"] != "normal"]
    configs = list(dict.fromkeys(anomalies["config"]))
    for ax, panel in zip(axes.ravel(), PHASE3_PANELS):
        subset = anomalies if panel == "all" else anomalies[anomalies["pattern"] == panel]
        data = subset.groupby(["config", x_key], as_index=False)["detection_rate"].mean()
        for config in configs:
            line = data[data["config"] == config].set_index(x_key).reindex(x_values)
            family = "OR" if config == "OR[top]" else _family(config)
            ax.plot(range(len(x_values)), line["detection_rate"], marker="o", ms=4, color=FAMILY_COLORS[family], linewidth=2.2 if family == "M1" else 1.6, label=config)
        ax.set_xticks(range(len(x_values)), x_labels)
        ax.set_ylim(-0.02, 1.02)
        ax.set_title("全パターン（B1〜B10）の平均" if panel == "all" else f"{panel} {SINGLE_WAFER_PATTERNS[panel]}", fontsize=8.5)
    for ax in axes[1]:
        ax.set_xlabel(xlabel)
    for ax in axes[:, 0]:
        ax.set_ylabel("平均検出率（1〜16σ_dir、FPR 1%）")
    axes[0, 0].legend(fontsize=6.5, loc="lower left")
    fig.suptitle(title, fontsize=10)
    fig.tight_layout()
    return save(fig, folder, name)


def figure8_points(metrics, folder):
    single = metrics["phase3_single"]
    levels = metrics["phase3_levels"]
    density_levels = levels[levels["factor"].isin(["base", "density"])].drop_duplicates("level")
    density = single[single["level"].isin(density_levels["level"])]
    points = density_levels.set_index("density")["n_points"].to_dict()
    values = sorted(density["density"].unique(), reverse=True)
    paths = _phase3_panels(
        density, "density", values, [f"{points.get(v, 0)} 点\n（{v:.0%}）" for v in values],
        "Figure 8 計測点数と検出率（実計測風の配置。異常の物理的な大きさは同じ、各条件 1,000 回）", folder, "figure08_measurement_points", "計測点数（全点に対する割合）",
    )
    layout_levels = levels[levels["factor"] == "layout"]
    layout = single[single["level"].isin(layout_levels["level"])]
    kinds = ["realistic", "uniform", "d_optimal", "i_optimal"]
    n_points = int(layout_levels["n_points"].iloc[0]) if len(layout_levels) else 0
    paths += _phase3_panels(
        layout, "layout", kinds, ["実計測風", "均等", "D最適", "I最適"],
        f"Figure 8b 計測配置と検出率（同じ点数：{n_points} 点＝全点の 25%）", folder, "figure08b_measurement_layout", "計測配置",
    )
    return paths


def figure9_noise(metrics, folder):
    single = metrics["phase3_single"]
    levels = metrics["phase3_levels"]
    noise_levels = levels[levels["factor"].isin(["base", "noise_scale"])].drop_duplicates("level")
    noise = single[single["level"].isin(noise_levels["level"])]
    values = sorted(noise["noise_scale"].unique())
    paths = _phase3_panels(
        noise, "noise_scale", values, [f"{v:g}×" for v in values],
        "Figure 9 計測ノイズと検出率（基準：Mark 1.0 nm・Shot 0.5 nm。異常の物理的な大きさは基準ノイズの σ_dir で固定）", folder, "figure09_measurement_noise", "計測ノイズの倍率",
    )
    temporal = metrics.get("phase3_temporal")
    if temporal is not None and len(temporal):
        fig, axes = plt.subplots(1, 2, figsize=(12, 4.2), sharey=True)
        temporal = temporal[temporal["pattern"] != "no_change"]
        info = levels.drop_duplicates("level").set_index("level")
        temporal = temporal.assign(noise_scale=temporal["level"].map(info["noise_scale"]), density=temporal["level"].map(info["density"]), layout=temporal["level"].map(info["layout"]), order=temporal["level"].map(info["order"]))
        for ax, (key, x_values, labels, xlabel) in zip(
            axes,
            (
                ("noise_scale", values, [f"{v:g}×" for v in values], "計測ノイズの倍率（全点）"),
                ("density", [1.0, 0.5, 0.25], ["316 点", "160 点", "80 点"], "計測点数（実計測風、ノイズ 1×）"),
            ),
        ):
            if key == "noise_scale":
                subset = temporal[(temporal["density"] == 1.0) & (temporal["order"] == "own")]
            else:
                subset = temporal[(temporal["noise_scale"] == 1.0) & (temporal["layout"] == "realistic") & (temporal["order"] == "own")]
            data = subset.groupby(["detector", key], as_index=False)["rmst_delay"].mean()
            for name in data["detector"].unique():
                line = data[data["detector"] == name].set_index(key).reindex(x_values)
                ax.plot(range(len(x_values)), line["rmst_delay"], label=name, **_detector_style(name))
            ax.set_xticks(range(len(x_values)), labels)
            ax.set_xlabel(xlabel)
        axes[0].set_ylabel("平均 RMST 遅延 [枚]（小さいほど早い）")
        axes[1].legend(fontsize=6.5)
        fig.suptitle("Figure 9b 計測条件と経時変化の検出遅延（A1・A2、低次・局所、0.5〜2σ_dir、ARL₀ = 370 で再校正）", fontsize=10)
        fig.tight_layout()
        paths += save(fig, folder, "figure09b_noise_points_temporal")
    return paths


# ---------------------------------------------------------------------- Figure 10（APC）
def figure10_apc(metrics, samples, folder, order=3):
    single = metrics["apc_single"]
    fig = plt.figure(figsize=(15, 8.5))
    grid = fig.add_gridspec(2, 4, height_ratios=[1, 1.05])
    scenario = "S2_cubic_radial"
    key = f"order{order}|{scenario}"
    if f"{key}|alignment" in samples:
        ax_, ay_ = samples[f"order{order}|alignment_x"], samples[f"order{order}|alignment_y"]
        ox, oy = samples[f"order{order}|overlay_x"], samples[f"order{order}|overlay_y"]
        alignment = samples[f"{key}|alignment"]
        before = samples[f"{key}|overlay_before"]
        correction = samples[f"{key}|correction_at_overlay"]
        residual = samples[f"{key}|residual"]
        magnitude = np.percentile(np.hypot(*split_xy(before)), 95)
        scale = 16.0 / magnitude
        keynm = nice_key(magnitude)
        vector_map(fig.add_subplot(grid[0, 0]), ax_, ay_, *split_xy(alignment), scale, "(a) 補正前 Alignment 計測値", key_nm=keynm)
        vector_map(fig.add_subplot(grid[0, 1]), ox, oy, *split_xy(before), scale, "(b) 補正前 Overlay（検証点）", key_nm=keynm)
        vector_map(fig.add_subplot(grid[0, 2]), ox, oy, *split_xy(correction), scale, f"(c) 補正モデル（{order}次）の補正量", color=FAMILY_COLORS["M2"], key_nm=keynm)
        vector_map(fig.add_subplot(grid[0, 3]), ox, oy, *split_xy(residual), scale, "(d) 補正後 Overlay 残差", color=FAMILY_COLORS["OR"], key_nm=keynm)
    data = single[(single["alignment_condition"] == "standard") & (single["scenario"] != "normal")]
    data = data.groupby(["correction_order", "scenario", "monitor", "target"], as_index=False)["detection_rate"].mean()
    scenarios = [s for s in ("S1_linear", "S2_cubic_radial", "S3_zernike89", "S3_local", "S3_single_shot", "S4_alignment_flyer") if s in data["scenario"].unique()]
    monitors = ["alignment:M3S", "alignment:T2", "coefficient:MD", "coefficient:SPC", "overlay:M3S", "overlay:T2", "overlay:SPE"]
    for col, correction_order in enumerate(sorted(data["correction_order"].unique())):
        ax = fig.add_subplot(grid[1, col])
        subset = data[data["correction_order"] == correction_order]
        matrix = subset.pivot(index="scenario", columns="monitor", values="detection_rate").reindex(index=scenarios, columns=monitors)
        image = ax.imshow(matrix.to_numpy(), cmap=SEQUENTIAL, vmin=0, vmax=1, aspect="auto")
        for i in range(matrix.shape[0]):
            for j in range(matrix.shape[1]):
                value = matrix.iat[i, j]
                if np.isfinite(value):
                    ax.text(j, i, f"{value:.2f}", ha="center", va="center", fontsize=6.5, color="white" if value > 0.55 else INK)
        ax.set_xticks(range(len(monitors)), [m.replace("alignment:", "補正前\n").replace("coefficient:", "補正係数\n").replace("overlay:", "残差\n") for m in monitors], fontsize=6.2)
        ax.set_yticks(range(len(scenarios)), scenarios if col == 0 else [""] * len(scenarios), fontsize=6.5)
        ax.grid(False)
        ax.set_title(f"(e{col + 1}) 補正 {correction_order} 次：検出率（1〜16σ_dir の平均）", fontsize=8.5)
    fig.colorbar(image, ax=fig.axes[-1], shrink=0.8)
    fig.suptitle("Figure 10 APC 補正前後の比較（上：3次の放射状歪み 8σ_dir の例、下：監視対象ごとの検出率、誤報率 1%）", fontsize=10)
    fig.tight_layout()
    return save(fig, folder, "figure10_apc_comparison")


# ---------------------------------------------------------------------- 付録の図
def appendix_figures(metrics, folder) -> list[Path]:
    paths = []
    if "phase1_b10_permutation" in metrics:
        perm = metrics["phase1_b10_permutation"]
        perm = perm[perm["alpha"] == 0.01]
        reps = representatives(metrics)
        names = list(reps["representative"])
        kinds = list(perm["kind"].unique())
        fig, ax = plt.subplots(figsize=(10, 3.8))
        width = 0.8 / len(names)
        for i, name in enumerate(names):
            values = perm[perm["detector"] == name].set_index("kind").reindex(kinds)["detection_rate"]
            ax.bar(np.arange(len(kinds)) + i * width - 0.4 + width / 2, values, width=width * 0.92, color=FAMILY_COLORS[_family(name)], label=name)
        ax.set_xticks(range(len(kinds)), ["180°回転", "左右反転", "上下反転", "無作為入れ替え"][: len(kinds)])
        ax.axhline(0.01, color=AXIS, linewidth=0.8)
        ax.set_ylabel("検出率（誤報率 1%）")
        ax.set_title("付録図A1 B10 方法1（計測値の位置入れ替え。M3S は厳密に同じ）")
        ax.legend(ncol=4, fontsize=6.5, loc="upper left")
        fig.tight_layout()
        paths += save(fig, folder, "appendix_a1_b10_permutation")
    if "phase2_rho_sweep" in metrics:
        sweep = metrics["phase2_rho_sweep"]
        sweep = sweep[sweep["pattern"] != "no_change"]
        data = sweep.groupby(["detector", "rho", "prewhiten"], as_index=False)["rmst_delay"].mean()
        fig, axes = plt.subplots(1, 2, figsize=(12, 4.2), sharey=True)
        for ax, prewhiten in zip(axes, (False, True)):
            subset = data[data["prewhiten"] == prewhiten]
            for name in subset["detector"].unique():
                line = subset[subset["detector"] == name].sort_values("rho")
                ax.plot(line["rho"], line["rmst_delay"], label=name, **_detector_style(name))
            ax.set_xlabel("正常工程の時系列相関 ρ")
            ax.set_title("AR(1) 残差で監視" if prewhiten else "計測値をそのまま監視", fontsize=8.5)
        axes[0].set_ylabel("平均 RMST 遅延 [枚]（A1・A2、低次・局所）")
        axes[1].legend(fontsize=6, ncol=2)
        fig.suptitle("付録図A2 時系列相関 ρ と検出遅延（ARL₀ = 370 で再校正）", fontsize=10)
        fig.tight_layout()
        paths += save(fig, folder, "appendix_a2_rho_sweep")
    if "phase1_auc" in metrics:
        auc = metrics["phase1_auc"]
        reps = representatives(metrics)
        columns = list(reps["representative"])
        matrix = auc[auc["detector"].isin(columns)].groupby(["pattern", "detector"])["roc_auc"].mean().unstack().reindex(index=list(SINGLE_WAFER_PATTERNS), columns=columns)
        fig, ax = plt.subplots(figsize=(10, 5))
        image = ax.imshow(matrix.to_numpy(), cmap=SEQUENTIAL, vmin=0.5, vmax=1, aspect="auto")
        for i in range(matrix.shape[0]):
            for j in range(matrix.shape[1]):
                v = matrix.iat[i, j]
                ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=7.5, color="white" if v > 0.8 else INK)
        ax.set_xticks(range(len(columns)), columns, fontsize=7, rotation=20)
        ax.set_yticks(range(len(matrix)), [f"{p} {SINGLE_WAFER_PATTERNS[p]}" for p in matrix.index], fontsize=7.5)
        ax.grid(False)
        fig.colorbar(image, ax=ax, shrink=0.8, label="ROC-AUC")
        ax.set_title("付録図A3 異常パターン別の ROC-AUC（全振幅の平均）")
        fig.tight_layout()
        paths += save(fig, folder, "appendix_a3_roc_auc")
    if "phase3_interaction" in metrics:
        inter = metrics["phase3_interaction"]
        inter = inter[(inter["pattern"] != "normal") & (inter["config"] != "M3S_XY") & (inter["monitor"] != "OR[top]")]
        effects = metrics["phase3_factor_effects"]
        a, b = list(effects["factor"].head(2))
        data = inter.groupby([a, b], as_index=False)["detection_rate"].mean()
        matrix = data.pivot(index=a, columns=b, values="detection_rate")
        fig, ax = plt.subplots(figsize=(6.5, 4))
        image = ax.imshow(matrix.to_numpy(), cmap=SEQUENTIAL, vmin=0, vmax=1, aspect="auto")
        for i in range(matrix.shape[0]):
            for j in range(matrix.shape[1]):
                v = matrix.iat[i, j]
                if np.isfinite(v):
                    ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=8, color="white" if v > 0.55 else INK)
        ax.set_xticks(range(matrix.shape[1]), [str(c) for c in matrix.columns])
        ax.set_yticks(range(matrix.shape[0]), [str(r) for r in matrix.index])
        ax.set_xlabel(b)
        ax.set_ylabel(a)
        ax.grid(False)
        fig.colorbar(image, ax=ax, shrink=0.8, label="平均検出率")
        ax.set_title("付録図A4 上位2因子の交互作用（上位の手法の平均検出率）", fontsize=9)
        fig.tight_layout()
        paths += save(fig, folder, "appendix_a4_interaction")
    return paths


# ---------------------------------------------------------------------- まとめて作る
def load_metrics(metrics_dir: Path) -> dict[str, pd.DataFrame]:
    return {path.stem: pd.read_parquet(path) for path in sorted(metrics_dir.glob("*.parquet"))}


def make_all(config: dict) -> list[Path]:
    setup_style()
    ctx = build_context(config)
    folder = ctx.out / "figures"
    metrics = load_metrics(ctx.out / "metrics")
    samples_dir = ctx.out / "samples"
    paths: list[Path] = []
    if (samples_dir / "phase1_examples.npz").exists():
        samples = dict(np.load(samples_dir / "phase1_examples.npz", allow_pickle=True))
        paths += figure1_normal(ctx, samples, folder)
        paths += figure2_anomalies(ctx, samples, folder)
        paths += figure3_b10(ctx, samples, metrics, folder)
    if "phase1_detection" in metrics:
        paths += figure4_detection_curves(metrics, folder)
        paths += figure5_heatmap(metrics, folder)
        paths += figure5_heatmap(metrics, folder, average=True, name="figure05b_pattern_heatmap_average")
    if (samples_dir / "phase2_example.npz").exists():
        paths += figure6_temporal_example(folder, dict(np.load(samples_dir / "phase2_example.npz", allow_pickle=True)))
    if "phase2_delays" in metrics:
        paths += figure7_delays(metrics, folder)
    if "phase3_single" in metrics:
        paths += figure8_points(metrics, folder)
        paths += figure9_noise(metrics, folder)
    if "apc_single" in metrics and (samples_dir / "apc_examples.npz").exists():
        paths += figure10_apc(metrics, dict(np.load(samples_dir / "apc_examples.npz", allow_pickle=True)), folder)
    paths += appendix_figures(metrics, folder)
    return paths
