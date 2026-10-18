"""「1. データ」の画面：ファイルを選ぶ → 列を対応づける → 読み込みの設定 → データを確認する。"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from ..columns import STANDARD_COLUMNS, auto_mapping
from ..loader import file_kind, list_sheets, read_table
from ..preprocess import column_value_counts, default_abnormal_values, prepare
from ..settings import DataOptions
from .widgets import PAD, SMALL_PAD, DataFrameTable, ScrollableFrame, ToolTip, labeled_row, read_float, set_text, show_error, text_box

NOT_USED = "（使わない）"
NO_COLUMN = "（なし）"
PREVIEW_ROWS = 100
FILE_TYPES = [("計測データ（CSV・Excel）", "*.csv *.txt *.tsv *.xlsx *.xlsm"), ("すべてのファイル", "*.*")]


class DataTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.columns: list[str] = []
        self._loading = False
        scroll = ScrollableFrame(self)
        scroll.pack(fill="both", expand=True)
        body = scroll.inner
        body.columnconfigure(0, weight=1)

        ttk.Label(body, text="1. 計測データを読み込む", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            body,
            text="Alignment または Overlay の計測テーブル（1行＝1つの Mark の計測）を選びます。"
            "データはこのパソコンの中だけで処理し、外部には送りません。",
            style="Note.TLabel", wraplength=1100, justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(0, PAD))

        file_box = ttk.LabelFrame(body, text="ファイル", padding=PAD)
        file_box.grid(row=2, column=0, sticky="ew", pady=SMALL_PAD)
        self.path_var = tk.StringVar()
        path_entry = ttk.Entry(file_box, textvariable=self.path_var, width=70, state="readonly")
        path_entry.grid(row=0, column=0, sticky="ew", padx=(0, PAD))
        self.choose_button = ttk.Button(file_box, text="ファイルを選ぶ…", command=self.choose_file)
        self.choose_button.grid(row=0, column=1)
        file_box.columnconfigure(0, weight=1)
        sheet_row = ttk.Frame(file_box)
        sheet_row.grid(row=1, column=0, columnspan=2, sticky="w", pady=(SMALL_PAD, 0))
        ttk.Label(sheet_row, text="シート（Excel のとき）").pack(side="left")
        self.sheet_var = tk.StringVar()
        self.sheet_box = ttk.Combobox(sheet_row, textvariable=self.sheet_var, state="disabled", width=30)
        self.sheet_box.pack(side="left", padx=PAD)
        self.sheet_box.bind("<<ComboboxSelected>>", lambda _e: self.load_table())
        ttk.Label(
            file_box,
            text="読み込めるのは CSV（.csv・.txt・.tsv、UTF-8 か Shift_JIS）と Excel（.xlsx・.xlsm）。古い .xls は Excel で .xlsx に保存し直してください。",
            style="Note.TLabel", wraplength=1100, justify="left",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(SMALL_PAD, 0))

        preview_box = ttk.LabelFrame(body, text=f"ファイルの中身（先頭 {PREVIEW_ROWS} 行）", padding=PAD)
        preview_box.grid(row=3, column=0, sticky="ew", pady=SMALL_PAD)
        self.preview = DataFrameTable(preview_box, height=6)
        self.preview.pack(fill="both", expand=True)

        mapping_box = ttk.LabelFrame(body, text="列の対応づけ（同じ名前の列は自動で選びます。違うときは選び直してください）", padding=PAD)
        mapping_box.grid(row=4, column=0, sticky="ew", pady=SMALL_PAD)
        self.mapping_vars: dict[str, tk.StringVar] = {}
        self.mapping_boxes: dict[str, ttk.Combobox] = {}
        for row, spec in enumerate(STANDARD_COLUMNS):
            mark = "（必須）" if spec.required else ""
            label = ttk.Label(mapping_box, text=f"{spec.name}{mark}")
            label.grid(row=row, column=0, sticky="w", padx=(0, PAD), pady=2)
            variable = tk.StringVar(value=NO_COLUMN)
            box = ttk.Combobox(mapping_box, textvariable=variable, state="readonly", width=22, values=[NO_COLUMN])
            box.grid(row=row, column=1, sticky="w", pady=2)
            box.bind("<<ComboboxSelected>>", lambda _e: self.options_changed())
            ttk.Label(mapping_box, text=f"{spec.meaning}［{spec.unit}］", style="Note.TLabel").grid(row=row, column=2, sticky="w", padx=(PAD, 0))
            ToolTip(label, f"{spec.name}：{spec.meaning}（単位・型：{spec.unit}）")
            self.mapping_vars[spec.name] = variable
            self.mapping_boxes[spec.name] = box

        options_box = ttk.LabelFrame(body, text="読み込みの設定", padding=PAD)
        options_box.grid(row=5, column=0, sticky="ew", pady=SMALL_PAD)
        self.unit_var = tk.StringVar(value="nm")
        unit_frame = ttk.Frame(options_box)
        for value, text in (("nm", "nm"), ("um", "µm（1000 倍して nm にする）")):
            ttk.Radiobutton(unit_frame, text=text, value=value, variable=self.unit_var, command=self.options_changed).pack(side="left", padx=(0, PAD))
        labeled_row(options_box, 0, "計測値（measX・measY）の単位", unit_frame)
        self.valid_radius_var = tk.StringVar(value="150")
        self.wafer_radius_var = tk.StringVar(value="150")
        self.tolerance_var = tk.StringVar(value="0.001")
        for row, (variable, label, note) in enumerate(
            (
                (self.valid_radius_var, "有効半径（mm）", "解析座標の半径がこの値より小さい点（r < 値）だけを使います。"),
                (self.wafer_radius_var, "Wafer の半径（mm）", "多項式・Zernike の正規化座標（x / R）の R。300 mm Wafer は 150。"),
                (self.tolerance_var, "座標の丸め幅（mm）", "この幅で丸めて同じ値になる座標は、同じ計測点とみなします。"),
            ),
            start=1,
        ):
            entry = ttk.Entry(options_box, textvariable=variable, width=10)
            entry.bind("<FocusOut>", lambda _e: self.options_changed())
            labeled_row(options_box, row, label, entry, note)
        self.remeasure_var = tk.StringVar(value="all")
        remeasure = ttk.Frame(options_box)
        for value, text in (("all", "すべて使う（別の計測として並べる）"), ("last", "最後の計測だけ使う")):
            ttk.Radiobutton(remeasure, text=text, value=value, variable=self.remeasure_var, command=self.options_changed).pack(side="left", padx=(0, PAD))
        labeled_row(options_box, 4, "同じ Wafer の計測が複数あるとき", remeasure)

        filter_box = ttk.LabelFrame(body, text="絞り込み（任意）：製品・工程・装置などが混ざっているときに、残す値を選びます", padding=PAD)
        filter_box.grid(row=6, column=0, sticky="ew", pady=SMALL_PAD)
        self.filter_column_var, self.filter_list = self._value_chooser(filter_box, "絞り込む列", "残す値（複数選べます）", self._filter_column_changed)

        label_box = ttk.LabelFrame(body, text="既知の異常のラベル（任意）：異常と分かっている Wafer の印の列があれば、手法の検出と照らし合わせます", padding=PAD)
        label_box.grid(row=7, column=0, sticky="ew", pady=SMALL_PAD)
        self.label_column_var, self.label_list = self._value_chooser(label_box, "ラベルの列", "「異常」を表す値（複数選べます）", self._label_column_changed)
        ttk.Label(
            label_box,
            text="ラベルで異常とされた計測は、正常のモデルの学習と管理限界の決定に使いません。",
            style="Note.TLabel",
        ).grid(row=2, column=0, columnspan=4, sticky="w")

        action = ttk.Frame(body)
        action.grid(row=8, column=0, sticky="ew", pady=(PAD, SMALL_PAD))
        self.check_button = ttk.Button(action, text="データを確認する", style="Primary.TButton", command=self.check_data)
        self.check_button.pack(side="left")
        self.next_button = ttk.Button(action, text="設定へ進む", command=lambda: self.app.select_tab(1), state="disabled")
        self.next_button.pack(side="left", padx=PAD)
        self.check_status = ttk.Label(action, text="ファイルを選んでください。", style="Note.TLabel")
        self.check_status.pack(side="left", padx=PAD)

        result_box = ttk.LabelFrame(body, text="データ確認の結果", padding=PAD)
        result_box.grid(row=9, column=0, sticky="ew", pady=SMALL_PAD)
        self.check_text = text_box(result_box, height=14)
        self.check_text.pack(fill="both", expand=True)
        self.set_busy(False)

    # ------------------------------------------------------------------ 部品
    def _value_chooser(self, parent, column_label: str, values_label: str, on_change):
        variable = tk.StringVar(value=NOT_USED)
        ttk.Label(parent, text=column_label).grid(row=0, column=0, sticky="nw", padx=(0, PAD))
        box = ttk.Combobox(parent, textvariable=variable, state="readonly", width=22, values=[NOT_USED])
        box.grid(row=0, column=1, sticky="nw")
        box.bind("<<ComboboxSelected>>", lambda _e: on_change())
        ttk.Label(parent, text=values_label).grid(row=0, column=2, sticky="nw", padx=(3 * PAD, PAD))
        frame = ttk.Frame(parent)
        frame.grid(row=0, column=3, sticky="w")
        listbox = tk.Listbox(frame, selectmode="multiple", exportselection=False, height=5, width=36)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=listbox.yview)
        listbox.configure(yscrollcommand=scrollbar.set)
        listbox.pack(side="left")
        scrollbar.pack(side="left", fill="y")
        listbox.bind("<<ListboxSelect>>", lambda _e: self.options_changed())
        buttons = ttk.Frame(parent)
        buttons.grid(row=1, column=3, sticky="w", pady=(SMALL_PAD, 0))
        ttk.Button(buttons, text="すべて選ぶ", command=lambda: (listbox.select_set(0, "end"), self.options_changed())).pack(side="left")
        ttk.Button(buttons, text="すべて外す", command=lambda: (listbox.select_clear(0, "end"), self.options_changed())).pack(side="left", padx=SMALL_PAD)
        listbox.values = []
        variable.box = box
        return variable, listbox

    def _fill_values(self, listbox: tk.Listbox, column: str, selected) -> None:
        listbox.delete(0, "end")
        listbox.values = []
        if column in (NOT_USED, "") or self.app.table is None:
            return
        for value, count in column_value_counts(self.app.table, column):
            listbox.insert("end", f"{value if value else '（空欄）'}（{count:,} 行）")
            listbox.values.append(value)
        for index, value in enumerate(listbox.values):
            if value in selected:
                listbox.select_set(index)

    @staticmethod
    def _selected_values(listbox: tk.Listbox) -> list[str]:
        return [listbox.values[index] for index in listbox.curselection()]

    def _filter_column_changed(self) -> None:
        column = self.filter_column_var.get()
        self._fill_values(self.filter_list, column, set())
        self.filter_list.select_set(0, "end")
        self.options_changed()

    def _label_column_changed(self) -> None:
        column = self.label_column_var.get()
        self._fill_values(self.label_list, column, set())
        chosen = set(default_abnormal_values(self.label_list.values))
        for index, value in enumerate(self.label_list.values):
            if value in chosen:
                self.label_list.select_set(index)
        self.options_changed()

    # ------------------------------------------------------------------ 操作
    def set_busy(self, busy: bool) -> None:
        state = ["disabled"] if busy else ["!disabled"]
        self.choose_button.state(state)
        has_table = self.app.table is not None
        self.check_button.state(["disabled"] if busy or not has_table else ["!disabled"])

    def choose_file(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="計測データのファイルを選ぶ", filetypes=FILE_TYPES)
        if path:
            self.load_path(path)

    def load_path(self, path: str, sheet: str | None = None) -> None:
        try:
            kind = file_kind(path)
            sheets = list_sheets(path) if kind == "excel" else []
        except Exception as error:  # 形式の誤りなど
            show_error(self, error)
            return
        self.path_var.set(path)
        self.sheet_box.configure(values=sheets, state="readonly" if sheets else "disabled")
        self.sheet_var.set(sheet if sheet in sheets else (sheets[0] if sheets else ""))
        self.load_table()

    def load_table(self) -> None:
        path = self.path_var.get()
        if not path:
            return
        sheet = self.sheet_var.get() or None

        def work(progress, cancel):
            return read_table(path, sheet, progress, cancel)

        self.app.run_task("ファイルを読み込んでいます", work, self._table_loaded)

    def _table_loaded(self, table) -> None:
        self.app.set_table(table, self.path_var.get(), self.sheet_var.get() or None)
        self.columns = [str(column) for column in table.columns]
        self.preview.show(table.head(PREVIEW_ROWS))
        saved = self.app.settings.data.mapping
        mapping = auto_mapping(self.columns)
        for name, column in saved.items():
            if column in self.columns:
                mapping[name] = column
        for name, box in self.mapping_boxes.items():
            box.configure(values=[NO_COLUMN] + self.columns)
            self.mapping_vars[name].set(mapping.get(name) or NO_COLUMN)
        for variable, listbox, column, selected in (
            (self.filter_column_var, self.filter_list, self.app.settings.data.filter_column, self.app.settings.data.filter_values),
            (self.label_column_var, self.label_list, self.app.settings.data.label_column, self.app.settings.data.label_abnormal_values),
        ):
            variable.box.configure(values=[NOT_USED] + self.columns)
            variable.set(column if column in self.columns else NOT_USED)
            self._fill_values(listbox, variable.get(), set(selected))
        self.check_status.configure(text=f"読み込みました（{len(table):,} 行・{len(self.columns)} 列）。列の対応づけを確かめて「データを確認する」を押してください。")
        self.app.set_status(f"{Path(self.path_var.get()).name} を読み込みました（{len(table):,} 行）")
        self.set_busy(False)
        self.options_changed()

    def options_changed(self) -> None:
        if self.app.prepared is not None:
            self.app.invalidate_prepared()
            self.check_status.configure(text="データの設定が変わりました。もう一度「データを確認する」を押してください。")
        self.next_button.state(["disabled"])

    def collect_options(self) -> DataOptions:
        options = DataOptions()
        options.file_path = self.path_var.get()
        options.sheet = self.sheet_var.get() or None
        options.mapping = {name: (variable.get() if variable.get() != NO_COLUMN else None) for name, variable in self.mapping_vars.items()}
        options.measurement_unit = self.unit_var.get()
        options.valid_radius_mm = read_float(self.valid_radius_var, "有効半径")
        options.wafer_radius_mm = read_float(self.wafer_radius_var, "Wafer の半径")
        options.coordinate_tolerance_mm = read_float(self.tolerance_var, "座標の丸め幅")
        options.remeasure_policy = self.remeasure_var.get()
        filter_column = self.filter_column_var.get()
        options.filter_column = None if filter_column == NOT_USED else filter_column
        options.filter_values = self._selected_values(self.filter_list) if options.filter_column else []
        label_column = self.label_column_var.get()
        options.label_column = None if label_column == NOT_USED else label_column
        options.label_abnormal_values = self._selected_values(self.label_list) if options.label_column else []
        return options

    def apply_options(self, options: DataOptions) -> None:
        """保存した設定を画面に反映する（ファイルの読み込みはしない）。"""
        self.unit_var.set(options.measurement_unit)
        self.valid_radius_var.set(f"{options.valid_radius_mm:g}")
        self.wafer_radius_var.set(f"{options.wafer_radius_mm:g}")
        self.tolerance_var.set(f"{options.coordinate_tolerance_mm:g}")
        self.remeasure_var.set(options.remeasure_policy)
        if self.app.table is not None:
            for name, variable in self.mapping_vars.items():
                column = options.mapping.get(name)
                if column in self.columns:
                    variable.set(column)
            for variable, listbox, column, selected in (
                (self.filter_column_var, self.filter_list, options.filter_column, options.filter_values),
                (self.label_column_var, self.label_list, options.label_column, options.label_abnormal_values),
            ):
                variable.set(column if column in self.columns else NOT_USED)
                self._fill_values(listbox, variable.get(), set(selected))
        self.options_changed()

    def check_data(self) -> None:
        if self.app.table is None:
            return
        try:
            options = self.collect_options()
        except Exception as error:
            show_error(self, error)
            return
        table = self.app.table

        def work(progress, cancel):
            progress(0.1, "前処理をしています（未測定の除外・重複の平均・有効半径）")
            return prepare(table, options)

        self.app.run_task("データを確認しています", work, lambda prepared: self._prepared(prepared, options))

    def _prepared(self, prepared, options: DataOptions) -> None:
        self.app.set_prepared(prepared, options)
        check = prepared.check
        lines = check.summary_lines()
        if check.warnings:
            lines += [""] + [f"注意：{text}" for text in check.warnings]
        set_text(self.check_text, "\n".join(lines))
        self.check_status.configure(text=f"確認できました（計測 {check.n_measurements:,} 件・計測点 {check.n_points:,} 点）。「設定へ進む」で次へ。")
        self.next_button.state(["!disabled"])
