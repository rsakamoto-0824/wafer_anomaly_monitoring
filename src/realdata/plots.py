"""結果の図（画面と保存の両方で使う）。pyplot を使わず Figure に直接描く（画面の部品に埋め込むため・別スレッドで安全なため）。

色だけで意味を伝えないように、警報は赤い「×」、ラベルの異常は「▲」、補った点は白抜きの丸と、形も変える。
手法の色は色覚の多様性に配慮した Okabe–Ito の配色を決まった順に使い、線の種類と点の形も変える。
"""
from __future__ import annotations

import numpy as np
from matplotlib import font_manager, rcParams
from matplotlib.figure import Figure
from matplotlib.patches import Circle
from matplotlib.ticker import NullLocator

from .dataset import SEGMENT_CALIBRATION, SEGMENT_EVALUATION, SEGMENT_LABEL_EXCLUDED, SEGMENT_TRAIN
from .injection import NO_ANOMALY, PATTERN_LABELS
from .settings import method_label

JAPANESE_FONTS = ("BIZ UDGothic", "BIZ UDPGothic", "Hiragino Sans", "Hiragino Kaku Gothic ProN", "Yu Gothic", "Meiryo", "Noto Sans CJK JP", "IPAexGothic")
SEGMENT_COLORS = {SEGMENT_TRAIN: "#E0E0E0", SEGMENT_CALIBRATION: "#D6E6F5", SEGMENT_LABEL_EXCLUDED: "#F3E5F5", SEGMENT_EVALUATION: "#FFFFFF"}
SEGMENT_LEGEND = {SEGMENT_TRAIN: "学習（学習に使ったので値が小さめ）"}
LINE_COLOR = "#1F4E79"
ALARM_COLOR = "#C62828"
THRESHOLD_COLOR = "#333333"
METHOD_COLORS = ("#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#7F3C8D", "#666666")
METHOD_MARKERS = ("o", "s", "^", "D", "v", "P", "X", "*")
METHOD_LINESTYLES = ("-", "--", "-.", ":")
M3S_STYLE = {"color": "#000000", "linestyle": "--", "marker": "o", "markerfacecolor": "white"}
WAFER_OUTLINE_COLOR = "#9E9E9E"
IMPUTED_COLOR = "#C62828"
MAP_LIMIT_MM = 158.0
LOG_SCALE_RATIO = 50.0  # 最大値が中央値のこの倍を超えたら縦軸を対数にする
ARROW_TARGET_MM = 12.0  # 矢印の長さの目安（大きいほうから1割の点がこのくらいの長さになるように）


def configure_fonts() -> str | None:
    """日本語の字形がある書体を使う（Mac・Windows のどちらでも見つかるものを順に探す）。"""
    available = {font.name for font in font_manager.fontManager.ttflist}
    chosen = [name for name in JAPANESE_FONTS if name in available][:1]  # 1つだけ（候補を並べると太さの警告が出る書体がある）
    rcParams["font.family"] = chosen + ["DejaVu Sans"]
    rcParams["axes.unicode_minus"] = False
    rcParams["font.size"] = 10
    return chosen[0] if chosen else None


def method_style(index: int, name: str) -> dict:
    if name == "M3S_XY":
        return dict(M3S_STYLE)
    return {
        "color": METHOD_COLORS[index % len(METHOD_COLORS)],
        "marker": METHOD_MARKERS[index % len(METHOD_MARKERS)],
        "linestyle": METHOD_LINESTYLES[(index // len(METHOD_COLORS)) % len(METHOD_LINESTYLES)],
    }


def _series(result, name: str):
    """（統計量, 管理限界, 警報）。1 Wafer の手法か、経時変化の検出器か。"""
    if name in result.scores:
        return result.scores[name].to_numpy(), result.thresholds[name], result.alarms[name].to_numpy(), "スコア"
    index = [detector.name for detector in result.temporal_detectors].index(name)
    return (
        result.temporal_stats[name].to_numpy(),
        float(result.temporal_thresholds[index]),
        result.temporal_alarms[name].to_numpy(),
        "統計量",
    )


def _segment_spans(orders: np.ndarray, segments: np.ndarray):
    spans = []
    start = 0
    for i in range(1, len(orders) + 1):
        if i == len(orders) or segments[i] != segments[start]:
            spans.append((segments[start], orders[start] - 0.5, orders[i - 1] + 0.5))
            start = i
    return spans


def control_chart(figure: Figure, result, name: str, log_scale: bool | None = None) -> None:
    figure.clear()
    figure.set_layout_engine("constrained")
    axes = figure.add_subplot(111)
    used = result.dataset.used
    orders = used["order"].to_numpy()
    values, threshold, alarms, ylabel = _series(result, name)
    shown_segments = set()
    for segment, low, high in _segment_spans(orders, used["segment"].to_numpy()):
        label = SEGMENT_LEGEND.get(segment, segment) if segment not in shown_segments else None
        shown_segments.add(segment)
        axes.axvspan(low, high, color=SEGMENT_COLORS.get(segment, "#FFFFFF"), alpha=1.0, lw=0, label=label, zorder=0)
    finite = np.isfinite(values)
    axes.plot(orders[finite], values[finite], color=LINE_COLOR, lw=0.8, marker="o", ms=2.5, label="値", zorder=2)
    hit = alarms & finite
    axes.plot(orders[hit], values[hit], linestyle="none", marker="x", ms=8, mew=2, color=ALARM_COLOR, label=f"警報（{hit.sum()} 件）", zorder=4)
    labeled = used["label"].to_numpy() & finite
    if labeled.any():
        top = np.nanmax(values[finite])
        axes.plot(orders[labeled], np.full(labeled.sum(), top), linestyle="none", marker="v", ms=9, color="#000000", label="ラベルで異常", zorder=5)
    axes.axhline(threshold, color=THRESHOLD_COLOR, lw=1.2, linestyle="--", label=f"管理限界 {threshold:.4g}", zorder=3)
    positive = values[finite]
    if log_scale is None:
        log_scale = bool(len(positive) and positive.min() > 0 and positive.max() > LOG_SCALE_RATIO * np.median(positive))
    if log_scale and len(positive) and positive.min() > 0:
        axes.set_yscale("log")
    axes.set_xlabel("計測の順番（時間の順）")
    axes.set_ylabel(ylabel)
    axes.set_title(result.label_of(name), loc="left", fontsize=11)
    axes.legend(loc="upper left", fontsize=8, ncol=3, framealpha=0.9)
    axes.grid(True, axis="y", color="#E0E0E0", lw=0.6)


def alarm_overview(figure: Figure, result, include_temporal: bool = True) -> None:
    """手法 × 計測の警報の一覧（黒い印＝警報）。校正期間より後だけを表示する。"""
    figure.clear()
    figure.set_layout_engine("constrained")
    axes = figure.add_subplot(111)
    used = result.dataset.used
    keep = used["segment"].isin([SEGMENT_CALIBRATION, SEGMENT_LABEL_EXCLUDED, SEGMENT_EVALUATION]).to_numpy()
    rows = used["row"].to_numpy()[keep]
    orders = used["order"].to_numpy()[keep]
    names = list(result.single_names)
    if include_temporal and result.temporal_alarms is not None:
        names += [detector.name for detector in result.temporal_detectors]
    matrix = []
    for name in names:
        source = result.alarms if name in result.alarms else result.temporal_alarms
        matrix.append(source[name].to_numpy()[rows])
    matrix = np.array(matrix, dtype=float)
    axes.imshow(matrix, aspect="auto", cmap="Greys", vmin=0, vmax=1, interpolation="nearest",
                extent=(orders.min() - 0.5, orders.max() + 0.5, len(names) - 0.5, -0.5))
    axes.set_yticks(range(len(names)))
    axes.set_yticklabels([_short_label(result.label_of(name)) for name in names], fontsize=7)
    evaluation = used["segment"].to_numpy()[keep] == SEGMENT_EVALUATION
    if evaluation.any():
        boundary = orders[evaluation].min() - 0.5
        axes.axvline(boundary, color=ALARM_COLOR, lw=1.2)
        axes.text(boundary, -0.6, " 評価期間 →", color=ALARM_COLOR, fontsize=8, va="bottom")
    axes.set_xlabel("計測の順番（黒い印＝警報）")
    axes.set_title("手法ごとの警報（校正期間から後）", loc="left", fontsize=11)


def _short_label(text: str, limit: int = 34) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def map_views(result) -> dict[str, str]:
    """Wafer マップで選べる表示（名前 → 画面に出す名前）。"""
    views = {"measured": "計測値（補った点は白抜きの丸）", "deviation": "正常時の平均との差"}
    if _raw_pca_monitor(result) is not None:
        views["pca_residual"] = "PCA で表せない成分（SPE の中身）"
    if _gpr_monitor(result) is not None:
        views["gpr_residual"] = "GPR の残差（滑らかな個体差を除いたもの）"
    return views


def _raw_pca_monitor(result):
    for monitor in result.monitors.values():
        model = getattr(monitor, "model", None)
        if model is not None and model.source == "raw":
            return monitor
    return None


def _gpr_monitor(result):
    for name, monitor in result.monitors.items():
        if name.startswith("GPR_"):
            return monitor
    return None


def map_vectors(result, row: int, view: str) -> np.ndarray:
    dataset = result.dataset
    filled = dataset.filled[row : row + 1]
    train = dataset.rows(SEGMENT_TRAIN)
    if view == "measured":
        vector = dataset.filled[row]
    elif view == "deviation":
        vector = dataset.filled[row] - dataset.filled[train].mean(axis=0)
    elif view == "pca_residual":
        vector = _raw_pca_monitor(result).model.residual(filled)[0]
    elif view == "gpr_residual":
        vector = _gpr_monitor(result).decompose(filled)["residual"][0]
    else:
        raise ValueError(f"未知の表示: {view}")
    n = dataset.n_points
    return np.column_stack([vector[:n], vector[n:]])


def nice_length(value: float) -> float:
    if not np.isfinite(value) or value <= 0:
        return 1.0
    exponent = np.floor(np.log10(value))
    for step in (1, 2, 5, 10):
        if step * 10**exponent >= value:
            return float(step * 10**exponent)
    return float(10 ** (exponent + 1))


def wafer_map(figure: Figure, result, row: int, view: str = "deviation", arrow_scale: float | None = None) -> float:
    """Wafer 面内の矢印の図。戻り値は使った矢印の倍率（mm / nm）。"""
    figure.clear()
    figure.set_layout_engine("constrained")
    axes = figure.add_subplot(111)
    dataset = result.dataset
    points = dataset.points
    vectors = map_vectors(result, row, view)
    magnitude = np.hypot(vectors[:, 0], vectors[:, 1])
    reference = nice_length(float(np.quantile(magnitude, 0.9))) if len(magnitude) else 1.0
    if arrow_scale is None:
        arrow_scale = ARROW_TARGET_MM / reference
    axes.add_patch(Circle((0, 0), dataset.prepared.options.wafer_radius_mm, fill=False, color=WAFER_OUTLINE_COLOR, lw=1.0))
    axes.plot(points.x_mm, points.y_mm, linestyle="none", marker=".", ms=2, color="#BDBDBD")
    axes.quiver(points.x_mm, points.y_mm, vectors[:, 0] * arrow_scale, vectors[:, 1] * arrow_scale,
                angles="xy", scale_units="xy", scale=1.0, width=0.0025, color=LINE_COLOR)
    imputed = np.isnan(dataset.observed[row])
    n = dataset.n_points
    imputed_point = imputed[:n] | imputed[n:]
    if imputed_point.any():
        axes.plot(points.x_mm[imputed_point], points.y_mm[imputed_point], linestyle="none", marker="o", ms=7,
                  markerfacecolor="none", markeredgecolor=IMPUTED_COLOR, mew=1.2, label=f"補った点（{imputed_point.sum()} 点）")
        axes.legend(loc="lower left", fontsize=8)
    key_mm = reference * arrow_scale
    axes.annotate("", xy=(-150 + key_mm, 150), xytext=(-150, 150), arrowprops={"arrowstyle": "->", "color": LINE_COLOR, "lw": 1.5})
    axes.text(-150, 153, f"{reference:g} nm", fontsize=9, color=LINE_COLOR)
    axes.set_xlim(-MAP_LIMIT_MM, MAP_LIMIT_MM)
    axes.set_ylim(-MAP_LIMIT_MM, MAP_LIMIT_MM + 8)
    axes.set_aspect("equal")
    axes.set_xlabel("x（mm）")
    axes.set_ylabel("y（mm）")
    used = dataset.used.reset_index(drop=True)
    info = used.loc[row]
    stamp = "" if str(info["DateTime"]) in ("NaT", "nan") else f"・{info['DateTime']:%Y/%m/%d %H:%M}"
    axes.set_title(f"{info['Wafer']}{stamp}（{info['segment']}）\n{map_views(result)[view]}", loc="left", fontsize=10)
    return arrow_scale


def injection_single_chart(figure: Figure, table, methods: list[str] | None = None) -> None:
    """パターンごとの「大きさ → 検出率」（同じ誤報率）。B10 は1水準なので最後の枠に横棒で出す。"""
    figure.clear()
    figure.set_layout_engine("constrained")
    if table is None or table.empty:
        return
    methods = methods or list(dict.fromkeys(table["method"]))
    patterns = [p for p in dict.fromkeys(table["pattern"]) if p not in (NO_ANOMALY, "B10")]
    has_b10 = "B10" in set(table["pattern"])
    panels = len(patterns) + (1 if has_b10 else 0)
    columns = 3
    rows = int(np.ceil(panels / columns))
    for number, pattern in enumerate(patterns):
        axes = figure.add_subplot(rows, columns, number + 1)
        subset = table[table["pattern"] == pattern]
        for index, method in enumerate(methods):
            line = subset[subset["method"] == method].sort_values("amplitude_sigma")
            if line.empty:
                continue
            axes.plot(line["amplitude_sigma"], line["detection_rate"], ms=4, lw=1.2, label=_short_label(method_label(method), 26), **method_style(index, method))
        axes.set_xscale("log", base=2)
        amplitudes = sorted(subset["amplitude_sigma"].dropna().unique())
        axes.set_xticks(amplitudes)
        axes.set_xticklabels([f"{value:g}" for value in amplitudes])
        axes.xaxis.set_minor_locator(NullLocator())
        axes.set_ylim(-0.03, 1.03)
        axes.set_title(f"{pattern} {PATTERN_LABELS.get(pattern, '')}", fontsize=8, loc="left")
        axes.grid(True, color="#E0E0E0", lw=0.5)
        axes.tick_params(labelsize=7)
        if number % columns == 0:
            axes.set_ylabel("検出率", fontsize=8)
        axes.set_xlabel("大きさ（σ_dir）", fontsize=7)
    if has_b10:
        axes = figure.add_subplot(rows, columns, panels)
        subset = table[table["pattern"] == "B10"].set_index("method").reindex(methods)
        axes.barh(range(len(methods)), subset["detection_rate"].to_numpy(), color="#90A4AE")
        axes.set_yticks(range(len(methods)))
        axes.set_yticklabels([_short_label(method_label(m), 18) for m in methods], fontsize=6)
        axes.set_xlim(0, 1)
        axes.invert_yaxis()
        axes.set_title("B10 点の入れ替え（平均・σ 不変）", fontsize=8, loc="left")
        axes.tick_params(labelsize=7)
    handles, labels = figure.axes[0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="outside lower center", ncol=min(4, len(labels)), fontsize=7, frameon=False)


def injection_temporal_chart(figure: Figure, summary) -> None:
    """検出器ごとの平均の制限付き平均遅延（RMST。小さいほど早く気づく）。"""
    figure.clear()
    figure.set_layout_engine("constrained")
    if summary is None or summary.empty:
        return
    axes = figure.add_subplot(111)
    ordered = summary.sort_values("mean_rmst_delay")
    y = np.arange(len(ordered))
    axes.barh(y, ordered["mean_rmst_delay"], color="#5C8DB8")
    for position, (rmst, rate, pre) in enumerate(zip(ordered["mean_rmst_delay"], ordered["mean_detection_rate"], ordered["pre_change_false_alarm_rate"])):
        axes.text(rmst, position, f"  {rmst:.1f} 枚（検出率 {rate:.0%}・変化前の誤報 {pre:.0%}）", va="center", fontsize=8)
    axes.set_yticks(y)
    axes.set_yticklabels([_short_label(label, 40) for label in ordered["detector_label"]], fontsize=8)
    axes.invert_yaxis()
    axes.set_xlabel("平均の検出遅延 RMST（枚。未検出は観測した枚数として数える）")
    axes.set_title("経時変化の注入試験：気づくまでの枚数（短いほど早い）", loc="left", fontsize=11)
    axes.set_xlim(0, float(ordered["mean_rmst_delay"].max()) * 1.6)
