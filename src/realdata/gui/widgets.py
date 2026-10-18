"""画面で何度も使う部品：スクロールできる枠、表、図、チェックボックスの組、説明の吹き出し、エラーの表示。"""
from __future__ import annotations

import sys
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox, ttk

import numpy as np
import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from ..errors import UserFacingError

IS_MAC = sys.platform == "darwin"
FONT_SIZES = {"小さめ": (14, 11), "標準": (16, 12), "大きめ": (18, 14)}  # （Mac, Windows）の pt。Windows の 12 pt ＝ 16 px
DEFAULT_FONT_SIZE = "標準"
PAD = 8
SMALL_PAD = 4
TABLE_MAX_ROWS = 5000
TABLE_MIN_WIDTH = 60
TABLE_MAX_WIDTH = 420
LOG_PATH = Path.home() / ".wafer_monitor_validator" / "log.txt"
NOTE_COLOR = "#37474F"
WARNING_COLOR = "#8D2A00"
TEXT_BACKGROUND = "#F7F9FB"
TEXT_FOREGROUND = "#1A1A1A"
NOTE_WRAP_PX = 900
_NAMED_FONTS: dict = {}  # tkinter の Font は Python 側の参照がなくなると消えるので、ここで持ち続ける


def use_light_appearance(window: tk.Misc) -> None:
    """Mac のダークモードでも明るい表示にする（Windows と同じ見た目にし、文字の色の組み合わせを保つ）。"""
    if not IS_MAC:
        return
    try:
        window.tk.call("::tk::unsupported::MacWindowStyle", "appearance", window._w, "aqua")
    except tk.TclError:
        pass


def text_box(parent, height: int) -> tk.Text:
    """読むだけの文章の欄（明るい背景に濃い文字。等幅ではない書体）。"""
    text = tk.Text(parent, height=height, wrap="word", relief="flat", background=TEXT_BACKGROUND, foreground=TEXT_FOREGROUND,
                   font="TkDefaultFont", padx=8, pady=6, spacing1=2, spacing3=2)
    text.configure(state="disabled")
    return text


def set_text(text: tk.Text, content: str) -> None:
    text.configure(state="normal")
    text.delete("1.0", "end")
    text.insert("1.0", content)
    text.configure(state="disabled")


def apply_font_size(root: tk.Misc, size_name: str) -> int:
    """アプリ全体の文字の大きさをそろえる（Tk の名前付きフォントを変える）。"""
    size = FONT_SIZES[size_name][0 if IS_MAC else 1]
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont", "TkTooltipFont", "TkFixedFont"):
        try:
            tkfont.nametofont(name, root=root).configure(size=size)
        except tk.TclError:
            pass
    heading = tkfont.nametofont("TkHeadingFont", root=root)
    heading.configure(weight="bold")
    family = tkfont.nametofont("TkDefaultFont", root=root).actual("family")
    for name, (extra, weight) in {"AppTitle": (4, "bold"), "AppSection": (1, "bold"), "AppBold": (0, "bold")}.items():
        if name not in _NAMED_FONTS:
            _NAMED_FONTS[name] = tkfont.Font(root=root, name=name, family=family)
        _NAMED_FONTS[name].configure(family=family, size=size + extra, weight=weight)
    style = ttk.Style(root)
    line = tkfont.nametofont("TkDefaultFont", root=root).metrics("linespace")
    style.configure("Treeview", rowheight=line + 6)
    style.configure("Title.TLabel", font="AppTitle")
    style.configure("Section.TLabel", font="AppSection")
    style.configure("Note.TLabel", foreground=NOTE_COLOR)
    style.configure("Warning.TLabel", foreground=WARNING_COLOR)
    style.configure("Primary.TButton", font="AppBold", padding=(16, 8))
    style.configure("TLabelframe.Label", font="AppSection")
    style.configure("TButton", padding=(10, 6))
    return size


def show_error(parent: tk.Misc, error: Exception) -> None:
    """エラーを「何が起きたか／なぜか／次にどうすればよいか」で出す。想定外のエラーはログにも残す。"""
    if isinstance(error, UserFacingError):
        messagebox.showerror("確認してください", f"{error.what}\n\n理由：{error.why}\n\n対処：{error.next_step}", parent=parent)
        return
    write_log("".join(traceback.format_exception(error)))
    messagebox.showerror(
        "予期しないエラー",
        f"処理の途中で予期しない問題が起きました（{type(error).__name__}：{error}）。\n\n"
        "理由：入力データか設定に、このアプリが想定していない形が含まれている可能性があります。\n\n"
        f"対処：設定を見直してもう一度試してください。続くときは、ログ（{LOG_PATH}）を開発者に渡してください。"
        "ログには計測値は含まれません。",
        parent=parent,
    )


def write_log(text: str) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as file:
            file.write(f"{pd.Timestamp.now():%Y/%m/%d %H:%M:%S}\n{text}\n")
    except OSError:
        pass


class ToolTip:
    """マウスを重ねたときと、キーボードで選んだときに出る短い説明。"""

    def __init__(self, widget: tk.Widget, text: str):
        self.widget = widget
        self.text = text
        self.window = None
        for event in ("<Enter>", "<FocusIn>"):
            widget.bind(event, self.show, add="+")
        for event in ("<Leave>", "<FocusOut>", "<ButtonPress>"):
            widget.bind(event, self.hide, add="+")

    def show(self, _event=None):
        if self.window is not None or not self.text:
            return
        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.window = tk.Toplevel(self.widget)
        use_light_appearance(self.window)
        self.window.wm_overrideredirect(True)
        self.window.wm_geometry(f"+{x}+{y}")
        ttk.Label(self.window, text=self.text, background="#FFFDE7", relief="solid", borderwidth=1, wraplength=480, padding=6).pack()

    def hide(self, _event=None):
        if self.window is not None:
            self.window.destroy()
            self.window = None


class ScrollableFrame(ttk.Frame):
    """縦にスクロールできる枠（設定の画面が長いので）。マウスのホイールでも動く。"""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, padding=PAD)
        self.inner.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._window, width=e.width))
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.bind_all("<MouseWheel>", self._on_wheel, add="+")
        self.bind_all("<Button-4>", self._on_wheel, add="+")
        self.bind_all("<Button-5>", self._on_wheel, add="+")

    def _on_wheel(self, event):
        widget = self.winfo_containing(event.x_root, event.y_root)
        while widget is not None and widget is not self:
            widget = widget.master
        if widget is None:
            return
        if event.num == 4:
            step = -1
        elif event.num == 5:
            step = 1
        else:
            step = -1 if event.delta > 0 else 1
            if not IS_MAC:
                step *= max(1, abs(event.delta) // 120)
        self.canvas.yview_scroll(step, "units")


class CheckGroup(ttk.Frame):
    """チェックボックスの組（値のリストを返す）。"""

    def __init__(self, parent, options: list[tuple[object, str]], selected=(), columns: int = 4, command=None, tooltips=None):
        super().__init__(parent)
        self.command = command
        self.variables: dict = {}
        self.buttons: dict = {}
        self.set_options(options, selected, columns, tooltips)

    def set_options(self, options, selected=(), columns: int = 4, tooltips=None):
        for child in self.winfo_children():
            child.destroy()
        self.variables, self.buttons = {}, {}
        selected = set(selected)
        for index, (value, text) in enumerate(options):
            variable = tk.BooleanVar(value=value in selected)
            button = ttk.Checkbutton(self, text=text, variable=variable, command=self._changed)
            button.grid(row=index // columns, column=index % columns, sticky="w", padx=(0, 16), pady=2)
            if tooltips and value in tooltips:
                ToolTip(button, tooltips[value])
            self.variables[value] = variable
            self.buttons[value] = button

    def _changed(self):
        if self.command is not None:
            self.command()

    def get(self) -> list:
        return [value for value, variable in self.variables.items() if variable.get()]

    def set(self, values) -> None:
        values = set(values)
        for value, variable in self.variables.items():
            variable.set(value in values)

    def set_state(self, enabled: bool) -> None:
        for button in self.buttons.values():
            button.state(["!disabled"] if enabled else ["disabled"])


class DataFrameTable(ttk.Frame):
    """DataFrame を表で出す（見出しを押すと並べ替え）。行が多いときは先頭の TABLE_MAX_ROWS 行だけ。"""

    def __init__(self, parent, height: int = 12, on_double_click=None):
        super().__init__(parent)
        self.tree = ttk.Treeview(self, show="headings", height=height, selectmode="browse")
        vertical = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.frame = pd.DataFrame()
        self.note = ttk.Label(self, style="Note.TLabel")
        self.note.grid(row=2, column=0, sticky="w")
        self._sort_state: dict = {}
        if on_double_click is not None:
            self.tree.bind("<Double-1>", lambda _e: self._double_click(on_double_click))
            self.tree.bind("<Return>", lambda _e: self._double_click(on_double_click))

    def show(self, frame: pd.DataFrame | None, note: str = "") -> None:
        self.tree.delete(*self.tree.get_children())
        frame = pd.DataFrame() if frame is None else frame
        self.frame = frame.reset_index(drop=True)
        columns = [str(column) for column in frame.columns]
        self.tree["columns"] = columns
        measure = tkfont.nametofont("TkDefaultFont").measure
        shown = self.frame.head(TABLE_MAX_ROWS)
        texts = [[format_cell(value) for value in row] for row in shown.itertuples(index=False)]
        for index, column in enumerate(columns):
            sample = [column] + [row[index] for row in texts[:200]]
            width = min(TABLE_MAX_WIDTH, max(TABLE_MIN_WIDTH, max(measure(text) for text in sample) + 24))
            self.tree.heading(column, text=column, command=lambda c=column: self._sort(c))
            self.tree.column(column, width=width, minwidth=TABLE_MIN_WIDTH, stretch=False, anchor="w")
        for row_number, row in enumerate(texts):
            self.tree.insert("", "end", iid=str(row_number), values=row)
        if len(frame) > TABLE_MAX_ROWS:
            note = (note + "　" if note else "") + f"（{len(frame):,} 行のうち先頭の {TABLE_MAX_ROWS:,} 行を表示。すべては保存したファイルで確認できます）"
        self.note.configure(text=note)

    def _sort(self, column: str) -> None:
        if self.frame.empty:
            return
        ascending = not self._sort_state.get(column, False)
        self._sort_state = {column: ascending}
        ordered = self.frame.sort_values(column, ascending=ascending, kind="stable", key=_sort_key)
        self.show(ordered, self.note.cget("text"))
        self._sort_state = {column: ascending}

    def selected_row(self) -> pd.Series | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return self.frame.iloc[int(selection[0])]

    def _double_click(self, callback) -> None:
        row = self.selected_row()
        if row is not None:
            callback(row)


def _sort_key(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric if numeric.notna().mean() > 0.5 else series.astype(str)


def format_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (float, np.floating)):
        if np.isnan(value):
            return ""
        if value != 0 and (abs(value) >= 1e5 or abs(value) < 1e-3):
            return f"{value:.4g}"
        return f"{value:.4g}" if abs(value) < 10 else f"{value:,.2f}".rstrip("0").rstrip(".")
    if isinstance(value, pd.Timestamp):
        return "" if pd.isna(value) else f"{value:%Y/%m/%d %H:%M:%S}"
    if isinstance(value, (bool, np.bool_)):
        return "はい" if value else ""
    return str(value)


class FigurePanel(ttk.Frame):
    """matplotlib の図と、拡大・移動・画像で保存のツールバー。"""

    def __init__(self, parent, size=(9, 4.5)):
        super().__init__(parent)
        self.figure = Figure(figsize=size, dpi=100, layout="constrained")
        self.canvas = FigureCanvasTkAgg(self.figure, master=self)
        toolbar_frame = ttk.Frame(self)
        toolbar_frame.pack(side="top", fill="x")
        self.toolbar = NavigationToolbar2Tk(self.canvas, toolbar_frame, pack_toolbar=False)
        self.toolbar.update()
        self.toolbar.pack(side="left")
        self.canvas.get_tk_widget().pack(side="top", fill="both", expand=True)

    def draw(self) -> None:
        self.canvas.draw_idle()
        self.toolbar.update()


def labeled_row(parent, row: int, label: str, widget: tk.Widget, note: str = "", tooltip: str = "") -> None:
    """ラベル（左）と入力（右）の1行。説明は入力の下に出す（ラベルは常に表示。プレースホルダーをラベルの代わりにしない）。

    1つの行が row（入力）と row + 1000（説明）の2段を使う。grid は空いた行を詰めるので、番号が飛んでも隙間はできない。
    """
    text = ttk.Label(parent, text=label)
    text.grid(row=row * 2, column=0, sticky="nw", padx=(0, PAD), pady=(SMALL_PAD, 0))
    widget.grid(row=row * 2, column=1, sticky="w", pady=(SMALL_PAD, 0))
    if note:
        ttk.Label(parent, text=note, style="Note.TLabel", wraplength=NOTE_WRAP_PX, justify="left").grid(
            row=row * 2 + 1, column=1, sticky="w", pady=(0, SMALL_PAD)
        )
    if tooltip:
        ToolTip(text, tooltip)
        ToolTip(widget, tooltip)


def read_float(variable: tk.Variable, name: str) -> float:
    text = str(variable.get()).strip().replace(",", "")
    try:
        return float(text)
    except ValueError as error:
        raise UserFacingError(f"「{name}」に数値でない値「{text}」が入っています。", "この項目は数値で指定します。", "半角の数字で入力し直してください（例 150）。") from error


def read_int(variable: tk.Variable, name: str) -> int:
    value = read_float(variable, name)
    if not float(value).is_integer():
        raise UserFacingError(f"「{name}」は整数で入力してください。", f"「{value:g}」は整数ではありません。", "小数点のない数字で入力し直してください。")
    return int(value)
