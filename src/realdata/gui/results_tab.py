"""「3. 結果」の画面：概要、管理図、警報の一覧、判定一覧、Wafer マップ、経時変化の管理限界、ラベルとの照合、注入試験。"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import numpy as np
import pandas as pd

from .. import plots
from ..dataset import SEGMENT_EVALUATION
from ..export import (
    INJECTION_SINGLE_SUMMARY_COLUMNS,
    INJECTION_TEMPORAL_SUMMARY_COLUMNS,
    LABEL_COLUMNS,
    METHOD_COLUMNS,
    TEMPORAL_COLUMNS,
    export_results,
    judgement_table,
)
from ..findings import key_findings
from ..injection import NO_ANOMALY, PATTERN_LABELS
from ..settings import method_label
from .widgets import PAD, SMALL_PAD, DataFrameTable, FigurePanel, format_cell, set_text, text_box

AXIS_CHOICES = {"自動": None, "線形": False, "対数": True}
ALL_PATTERNS = "すべてのパターン（小さな図を並べる）"
DRIFT_CHART_LIMIT = 10  # 画面の図に出す検出器の数（ノート PC の画面でも名前が重ならないように。保存する図はすべて）
VIEW_HINT = "表の行をダブルクリック（または Enter）すると、その計測の Wafer マップを表示します。"


class ResultsTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.result = None
        header = ttk.Frame(self, padding=(PAD, PAD, PAD, 0))
        header.pack(fill="x")
        ttk.Label(header, text="3. 検証の結果", style="Title.TLabel").pack(side="left")
        self.save_button = ttk.Button(header, text="結果を保存…", style="Primary.TButton", command=self.save)
        self.save_button.pack(side="right")
        self.title = ttk.Label(self, text="", style="Note.TLabel", padding=(PAD, 0))
        self.title.pack(fill="x")
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=PAD, pady=PAD)
        self.pages: dict[str, ttk.Frame] = {}
        for key, text in (
            ("summary", "概要"),
            ("chart", "管理図"),
            ("overview", "警報の一覧"),
            ("table", "判定一覧"),
            ("map", "マップ"),
            ("temporal", "経時の限界"),
            ("label", "ラベル照合"),
            ("single", "注入 1 Wafer"),
            ("drift", "注入 経時変化"),
        ):
            page = ttk.Frame(self.notebook, padding=PAD)
            self.notebook.add(page, text=text)
            self.pages[key] = page
        self._build_summary()
        self._build_chart()
        self._build_overview()
        self._build_table()
        self._build_map()
        self._build_simple_table("temporal", "ARL₀ を目標にそろえた管理限界と、実データでの警報の数です。校正の警報数は「件数 ÷ ARL₀」がおよその目安です。")
        self._build_simple_table("label", "陽性＝ラベルで異常の計測、陰性＝評価期間のラベルのない計測です（陰性には、まだ気づいていない異常が混じることがあります）。")
        self._build_injection("single", "検証と同じ形の異常を、校正期間の正常 Wafer に足したときの検出率です（同じ誤報率）。")
        self._build_injection("drift", "校正期間の Wafer をつないだ系列の途中から異常が増えたとき、気づくまでの枚数です（同じ ARL₀）。")
        self.set_busy(False)

    # ------------------------------------------------------------------ ページの組み立て
    def _build_summary(self):
        page = self.pages["summary"]
        panes = ttk.Panedwindow(page, orient="vertical")
        panes.pack(fill="both", expand=True)
        top = ttk.Frame(panes)
        self.summary_text = text_box(top, height=11)
        scrollbar = ttk.Scrollbar(top, orient="vertical", command=self.summary_text.yview)
        self.summary_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.summary_text.pack(side="left", fill="both", expand=True)
        panes.add(top, weight=1)
        bottom = ttk.Frame(panes)
        ttk.Label(bottom, text="手法ごとの管理限界と警報の数（1 Wafer）", style="Section.TLabel").pack(anchor="w", pady=(PAD, SMALL_PAD))
        self.method_table = DataFrameTable(bottom, height=6)
        self.method_table.pack(fill="both", expand=True)
        panes.add(bottom, weight=1)

    def _build_chart(self):
        page = self.pages["chart"]
        controls = ttk.Frame(page)
        controls.pack(fill="x")
        ttk.Label(controls, text="手法").pack(side="left")
        self.chart_var = tk.StringVar()
        self.chart_box = ttk.Combobox(controls, textvariable=self.chart_var, state="readonly", width=60)
        self.chart_box.pack(side="left", padx=PAD)
        self.chart_box.bind("<<ComboboxSelected>>", lambda _e: self.draw_chart())
        ttk.Label(controls, text="縦軸").pack(side="left", padx=(PAD, 0))
        self.axis_var = tk.StringVar(value="自動")
        axis = ttk.Combobox(controls, textvariable=self.axis_var, state="readonly", width=6, values=list(AXIS_CHOICES))
        axis.pack(side="left", padx=PAD)
        axis.bind("<<ComboboxSelected>>", lambda _e: self.draw_chart())
        ttk.Label(page, text="灰色＝学習、水色＝校正、白＝評価。赤い × が警報、▼ がラベルで異常の計測です。", style="Note.TLabel").pack(anchor="w", pady=SMALL_PAD)
        self.chart_panel = FigurePanel(page, size=(10, 4.6))
        self.chart_panel.pack(fill="both", expand=True)
        self._chart_names: dict[str, str] = {}

    def _build_overview(self):
        page = self.pages["overview"]
        self.overview_temporal_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(page, text="経時変化の検出器も表示する", variable=self.overview_temporal_var, command=self.draw_overview).pack(anchor="w")
        self.overview_panel = FigurePanel(page, size=(10, 6))
        self.overview_panel.pack(fill="both", expand=True)

    def _build_table(self):
        page = self.pages["table"]
        controls = ttk.Frame(page)
        controls.pack(fill="x")
        self.only_alarm_var = tk.BooleanVar(value=False)
        self.without_m3s_var = tk.BooleanVar(value=False)
        self.evaluation_only_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(controls, text="警報が1つ以上ある計測だけ", variable=self.only_alarm_var, command=self.fill_table).pack(side="left")
        ttk.Checkbutton(controls, text="M3S は警報なし・ほかで警報あり の計測だけ", variable=self.without_m3s_var, command=self.fill_table).pack(side="left", padx=PAD)
        ttk.Checkbutton(controls, text="評価期間だけ", variable=self.evaluation_only_var, command=self.fill_table).pack(side="left", padx=PAD)
        ttk.Label(page, text=VIEW_HINT, style="Note.TLabel").pack(anchor="w", pady=SMALL_PAD)
        self.judgement = DataFrameTable(page, height=18, on_double_click=self._open_map_from_row)
        self.judgement.pack(fill="both", expand=True)

    def _build_map(self):
        page = self.pages["map"]
        controls = ttk.Frame(page)
        controls.pack(fill="x")
        ttk.Label(controls, text="計測").pack(side="left")
        self.wafer_var = tk.StringVar()
        self.wafer_box = ttk.Combobox(controls, textvariable=self.wafer_var, state="readonly", width=46)
        self.wafer_box.pack(side="left", padx=PAD)
        self.wafer_box.bind("<<ComboboxSelected>>", lambda _e: self.draw_map())
        ttk.Button(controls, text="前へ", command=lambda: self._step_map(-1)).pack(side="left")
        ttk.Button(controls, text="次へ", command=lambda: self._step_map(1)).pack(side="left", padx=SMALL_PAD)
        ttk.Label(controls, text="表示").pack(side="left", padx=(PAD, 0))
        self.view_var = tk.StringVar()
        self.view_box = ttk.Combobox(controls, textvariable=self.view_var, state="readonly", width=34)
        self.view_box.pack(side="left", padx=PAD)
        self.view_box.bind("<<ComboboxSelected>>", lambda _e: self.draw_map())
        body = ttk.Panedwindow(page, orient="horizontal")
        body.pack(fill="both", expand=True, pady=SMALL_PAD)
        self.map_panel = FigurePanel(body, size=(6.4, 6.4))
        body.add(self.map_panel, weight=3)
        side = ttk.Frame(body, padding=(PAD, 0))
        body.add(side, weight=2)
        ttk.Label(side, text="この計測の判定", style="Section.TLabel").pack(anchor="w")
        self.map_table = DataFrameTable(side, height=16)
        self.map_table.pack(fill="both", expand=True)
        self._views: dict[str, str] = {}
        self._wafer_rows: list[int] = []

    def _build_simple_table(self, key: str, note: str):
        page = self.pages[key]
        ttk.Label(page, text=note, style="Note.TLabel", wraplength=1100, justify="left").pack(anchor="w", pady=(0, SMALL_PAD))
        table = DataFrameTable(page, height=16)
        table.pack(fill="both", expand=True)
        setattr(self, f"{key}_table", table)

    def _build_injection(self, key: str, note: str):
        """図と表を別のタブにする（ノート PC の画面でも、図を画面いっぱいに出せるように）。"""
        page = self.pages[key]
        ttk.Label(page, text=note, style="Note.TLabel", wraplength=1100, justify="left").pack(anchor="w")
        inner = ttk.Notebook(page)
        inner.pack(fill="both", expand=True, pady=(SMALL_PAD, 0))
        figure_page = ttk.Frame(inner, padding=SMALL_PAD)
        table_page = ttk.Frame(inner, padding=SMALL_PAD)
        inner.add(figure_page, text="図")
        inner.add(table_page, text="表（手法ごとのまとめ）")
        table = DataFrameTable(table_page, height=12)
        table.pack(fill="both", expand=True)
        ttk.Label(table_page, text="条件ごとのくわしい表は、「結果を保存…」で保存した Excel にあります。", style="Note.TLabel").pack(anchor="w")
        if key == "single":
            controls = ttk.Frame(figure_page)
            controls.pack(fill="x")
            ttk.Label(controls, text="図にするパターン").pack(side="left")
            self.pattern_var = tk.StringVar()
            self.pattern_box = ttk.Combobox(controls, textvariable=self.pattern_var, state="readonly", width=46)
            self.pattern_box.pack(side="left", padx=PAD)
            self.pattern_box.bind("<<ComboboxSelected>>", lambda _e: self.draw_single())
            self._patterns: dict[str, str | None] = {}
        panel = FigurePanel(figure_page, size=(10, 5))
        panel.pack(fill="both", expand=True)
        setattr(self, f"{key}_table", table)
        setattr(self, f"{key}_panel", panel)

    # ------------------------------------------------------------------ 結果を表示する
    def set_busy(self, busy: bool) -> None:
        self.save_button.state(["disabled"] if busy or self.result is None else ["!disabled"])

    def show(self, result) -> None:
        self.result = result
        source = Path(result.settings.data.file_path).name or "（ファイル名なし）"
        self.title.configure(text=f"ファイル：{source}　誤報率 {result.settings.methods.alpha_percent:g}%"
                             + (f"・ARL₀ {result.settings.temporal.target_arl0:g} 枚" if result.temporal_detectors else ""))
        self._fill_summary()
        names = list(result.single_names) + [d.name for d in result.temporal_detectors]
        self._chart_names = {result.label_of(name): name for name in names}
        self.chart_box.configure(values=list(self._chart_names))
        self.chart_var.set(next(iter(self._chart_names)))
        self.draw_chart()
        self.draw_overview()
        self.fill_table()
        self._views = {text: key for key, text in plots.map_views(result).items()}
        self.view_box.configure(values=list(self._views))
        self.view_var.set(list(self._views)[1])
        used = result.dataset.used.reset_index(drop=True)
        self._wafer_rows = list(range(len(used)))
        self.wafer_box.configure(values=[self._wafer_text(used.loc[row]) for row in self._wafer_rows])
        first_alarm = np.flatnonzero(result.alarms.to_numpy().any(axis=1) & (used["segment"] == SEGMENT_EVALUATION).to_numpy())
        self.wafer_box.current(int(first_alarm[0]) if len(first_alarm) else 0)
        self.draw_map()
        self._show_optional("temporal", result.temporal_table, TEMPORAL_COLUMNS)
        self._show_optional("label", result.label_table, LABEL_COLUMNS)
        single = result.injection_single_summary
        if single is not None and not single.empty:
            single = single.assign(method_label=single["method"].map(method_label))
        self._show_optional("single", single, INJECTION_SINGLE_SUMMARY_COLUMNS)
        if result.injection_single is not None:
            patterns = [p for p in dict.fromkeys(result.injection_single["pattern"]) if p != NO_ANOMALY]
            self._patterns = {f"{p} {PATTERN_LABELS.get(p, '')}": p for p in patterns}
            self._patterns[ALL_PATTERNS] = None
            self.pattern_box.configure(values=list(self._patterns))
            self.pattern_var.set(next(iter(self._patterns)))
            self.draw_single()
        self._show_optional("drift", result.injection_temporal_summary, INJECTION_TEMPORAL_SUMMARY_COLUMNS)
        if result.injection_temporal_summary is not None:
            plots.injection_temporal_chart(self.drift_panel.figure, result.injection_temporal_summary, DRIFT_CHART_LIMIT)
            self.drift_panel.draw()
        self.notebook.select(self.pages["summary"])
        self.set_busy(False)

    def _show_optional(self, key: str, table, columns: dict) -> None:
        page = self.pages[key]
        if table is None or table.empty:
            self.notebook.hide(page)
            return
        self.notebook.add(page)  # 隠していたページを元に戻す
        present = [column for column in columns if column in table.columns]
        getattr(self, f"{key}_table").show(table[present].rename(columns=columns))

    def _fill_summary(self) -> None:
        result = self.result
        lines = ["【要点】"] + [f"・{line}" for line in key_findings(result)]
        warnings = result.warnings + result.dataset.prepared.check.warnings
        if warnings:
            lines += ["", "【注意】"] + [f"・{text}" for text in warnings]
        if result.skipped_methods:
            lines += ["", "【使わなかった手法】"] + [f"・{method_label(n)}：{r}" for n, r in result.skipped_methods]
        set_text(self.summary_text, "\n".join(lines))
        present = [column for column in METHOD_COLUMNS if column in result.method_table.columns]
        self.method_table.show(result.method_table[present].rename(columns=METHOD_COLUMNS))

    def draw_single(self) -> None:
        if self.result is None or self.result.injection_single is None:
            return
        pattern = self._patterns.get(self.pattern_var.get())
        plots.injection_single_chart(self.single_panel.figure, self.result.injection_single, pattern=pattern)
        self.single_panel.draw()

    def draw_chart(self) -> None:
        if self.result is None or not self.chart_var.get():
            return
        plots.control_chart(self.chart_panel.figure, self.result, self._chart_names[self.chart_var.get()], AXIS_CHOICES[self.axis_var.get()])
        self.chart_panel.draw()

    def draw_overview(self) -> None:
        if self.result is None:
            return
        plots.alarm_overview(self.overview_panel.figure, self.result, self.overview_temporal_var.get())
        self.overview_panel.draw()

    def fill_table(self) -> None:
        if self.result is None:
            return
        table = judgement_table(self.result)
        keep = pd.Series(True, index=table.index)
        alarms = self.result.alarms
        if self.only_alarm_var.get():
            keep &= alarms.any(axis=1).to_numpy()
        if self.without_m3s_var.get() and "M3S_XY" in alarms:
            others = [name for name in self.result.single_names if name != "M3S_XY"]
            keep &= (~alarms["M3S_XY"] & alarms[others].any(axis=1)).to_numpy()
        if self.evaluation_only_var.get():
            keep &= (table["区分"] == SEGMENT_EVALUATION).to_numpy()
        columns = [c for c in table.columns if not c.endswith("のスコア")]
        self.judgement.show(table.loc[keep, columns], note=f"{int(keep.sum()):,} 件")

    def _open_map_from_row(self, row: pd.Series) -> None:
        used = self.result.dataset.used.reset_index(drop=True)
        position = used.index[used["order"] == row["順番"]]
        if len(position):
            self.wafer_box.current(int(position[0]))
            self.draw_map()
            self.notebook.select(self.pages["map"])

    def _step_map(self, step: int) -> None:
        if self.result is None:
            return
        index = max(0, min(len(self._wafer_rows) - 1, self.wafer_box.current() + step))
        self.wafer_box.current(index)
        self.draw_map()

    @staticmethod
    def _wafer_text(row: pd.Series) -> str:
        stamp = "" if pd.isna(row["DateTime"]) else f"・{row['DateTime']:%Y/%m/%d %H:%M}"
        return f"{int(row['order'])}：{row['Wafer']}{stamp}（{row['segment']}）"

    def draw_map(self) -> None:
        if self.result is None or self.wafer_box.current() < 0:
            return
        row = self._wafer_rows[self.wafer_box.current()]
        plots.wafer_map(self.map_panel.figure, self.result, row, self._views.get(self.view_var.get(), "deviation"))
        self.map_panel.draw()
        rows = []
        for name in self.result.single_names:
            rows.append({"手法": method_label(name), "判定": "警報" if self.result.alarms[name].iloc[row] else "",
                         "スコア": self.result.scores[name].iloc[row], "管理限界": self.result.thresholds[name]})
        for index, detector in enumerate(self.result.temporal_detectors):
            value = self.result.temporal_stats[detector.name].iloc[row]
            rows.append({"手法": self.result.label_of(detector.name),
                         "判定": "警報" if self.result.temporal_alarms[detector.name].iloc[row] else ("（対象外）" if np.isnan(value) else ""),
                         "スコア": value, "管理限界": float(self.result.temporal_thresholds[index])})
        info = self.result.dataset.used.reset_index(drop=True).loc[row]
        note = f"M3S X {format_cell(self.result.m3s_values['M3S_X_nm'].iloc[row])} nm・Y {format_cell(self.result.m3s_values['M3S_Y_nm'].iloc[row])} nm、補った値 {int(info['n_imputed'])} 個"
        self.map_table.show(pd.DataFrame(rows), note=note)

    # ------------------------------------------------------------------ 保存
    def save(self) -> None:
        if self.result is None:
            return
        folder = filedialog.askdirectory(parent=self, title="結果を保存するフォルダを選ぶ（中に新しいフォルダを作ります）")
        if not folder:
            return
        result = self.result
        source = Path(result.settings.data.file_path).name

        def work(progress, cancel):
            return export_results(result, folder, source, progress)

        self.app.run_task("結果を保存しています", work, self._saved)

    def _saved(self, folder: Path) -> None:
        self.app.set_status(f"保存しました：{folder}")
        self.app.notify_saved(folder)
