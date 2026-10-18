"""検証アプリの本体（主な画面、時間のかかる処理、メニュー、自己診断）。

時間のかかる処理（読み込み・前処理・検証・保存）は別のスレッドで動かし、画面は 0.1 秒ごとに進み具合を受け取って更新する
（Tkinter の部品は画面のスレッドからしか触らない）。計算中は「中止」で止められる。

起動のしかた
- 画面：python -m src.realdata.gui.app（または realdata_validator/run_app.py）
- 自己診断（画面なし）：--self-test 出力先フォルダ。練習用データで 読み込み → 検証 → 保存 までを試し、結果を self_test_result.txt に書く
- 画面の自己診断：--gui-smoke-test 出力先フォルダ。同じ流れを画面の部品を通して行い、終わったら閉じる
"""
from __future__ import annotations

import argparse
import queue
import sys
import threading
import tkinter as tk
import traceback
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .. import plots
from ..errors import AnalysisCancelled, UserFacingError
from ..export import APP_NAME, APP_VERSION
from ..settings import AppSettings, load_settings, save_settings
from .data_tab import DataTab
from .results_tab import ResultsTab
from .settings_tab import SettingsTab
from .widgets import (
    DEFAULT_FONT_SIZE,
    FONT_SIZES,
    LOG_PATH,
    PAD,
    SMALL_PAD,
    apply_font_size,
    labeled_row,
    read_int,
    set_text,
    show_error,
    text_box,
    use_light_appearance,
)

POLL_MS = 100
WINDOW_SIZE = "1360x900"
MIN_WINDOW = (1000, 680)
SELF_TEST_LOTS = 12
SELF_TEST_EXCEL_LOTS = 4
SMOKE_TEST_TIMEOUT_S = 900
TAB_DATA, TAB_SETTINGS, TAB_RESULTS = 0, 1, 2
HELP_TEXT = """使い方（3つの手順）

1. データ
   「ファイルを選ぶ…」で計測テーブル（CSV・Excel）を選びます。1行が1つの Mark の計測で、
   Wafer・DateTime・Xmm・Ymm・markXmm・markYmm・measX・measY・StsX・StsY などの列がある形です。
   同じ名前の列は自動で対応づけます。違う名前のときは選び直してください。
   「データを確認する」を押すと、未測定（Sts = −1）の除外、重複行の平均、有効半径の外の除外をして、件数を表示します。

2. 設定
   正常期間（異常がないと考えられる期間）を、先頭からの割合・件数・日時で決めます。
   その前半で正常のモデルを学習し、後半で管理限界を決め、それより後の計測を評価します。
   手法と誤報率を選び、「検証を実行」を押します。既定の値は模擬データの検証と同じです。

3. 結果
   概要・管理図・判定一覧・Wafer マップなどで結果を確かめ、「結果を保存…」で Excel・CSV・図を保存します。

注入試験について
   実データには、どの Wafer が異常かの正解がふつうはありません。そこで、校正期間の正常 Wafer に、
   検証と同じ形の異常（Radial・局所・単一 Shot など）を足して、同じ誤報率で検出率を比べます。

データの扱い
   データはこのパソコンの中だけで処理し、インターネットには送りません。
   保存した結果には実データの値が含まれるので、社外のサービスや公開の場所に置かないでください。
"""


class BackgroundTask:
    """関数を別のスレッドで動かし、進み具合と結果をキューで画面に渡す。"""

    def __init__(self, function):
        self.queue: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.thread = threading.Thread(target=self._run, args=(function,), daemon=True)
        self.thread.start()

    def _run(self, function):
        try:
            self.queue.put(("done", function(self._progress, self.cancel)))
        except AnalysisCancelled:
            self.queue.put(("cancelled", None))
        except UserFacingError as error:
            self.queue.put(("error", error))
        except Exception as error:  # 想定外のエラーも画面で知らせる
            self.queue.put(("error", error))

    def _progress(self, fraction: float, message: str) -> None:
        self.queue.put(("progress", (fraction, message)))


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings = AppSettings()
        self.table = None
        self.prepared = None
        self.result = None
        self.task: BackgroundTask | None = None
        self.on_done = None
        self.task_listeners = []
        use_light_appearance(root)
        root.title(f"{APP_NAME}（{APP_VERSION}）")
        root.geometry(WINDOW_SIZE)
        root.minsize(*MIN_WINDOW)
        self.font_size = tk.StringVar(value=DEFAULT_FONT_SIZE)
        apply_font_size(root, DEFAULT_FONT_SIZE)
        plots.configure_fonts()
        self._build_menu()
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=PAD, pady=(PAD, 0))
        self.data_tab = DataTab(self.notebook, self)
        self.settings_tab = SettingsTab(self.notebook, self)
        self.results_tab = ResultsTab(self.notebook, self)
        self.notebook.add(self.data_tab, text="1. データ")
        self.notebook.add(self.settings_tab, text="2. 設定")
        self.notebook.add(self.results_tab, text="3. 結果")
        self.notebook.tab(TAB_SETTINGS, state="disabled")
        self.notebook.tab(TAB_RESULTS, state="disabled")
        self._build_status_bar()
        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.bind("<Escape>", lambda _e: self.cancel_task())

    # ------------------------------------------------------------------ 画面の組み立て
    def _build_menu(self) -> None:
        menu = tk.Menu(self.root)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="データを開く…", command=lambda: self.data_tab.choose_file())
        file_menu.add_separator()
        file_menu.add_command(label="設定を読み込む…", command=self.load_settings_file)
        file_menu.add_command(label="設定を保存…", command=self.save_settings_file)
        file_menu.add_separator()
        file_menu.add_command(label="結果を保存…", command=lambda: self.results_tab.save())
        file_menu.add_separator()
        file_menu.add_command(label="終了", command=self.quit)
        menu.add_cascade(label="ファイル", menu=file_menu)
        view_menu = tk.Menu(menu, tearoff=False)
        for name in FONT_SIZES:
            view_menu.add_radiobutton(label=f"文字の大きさ：{name}", variable=self.font_size, value=name, command=self._font_changed)
        menu.add_cascade(label="表示", menu=view_menu)
        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="使い方", command=self.show_help)
        help_menu.add_command(label="練習用の模擬データを作る…", command=self.make_sample_dialog)
        help_menu.add_command(label="ログのフォルダを開く", command=self.open_log_folder)
        help_menu.add_command(label="このアプリについて", command=self.show_about)
        menu.add_cascade(label="ヘルプ", menu=help_menu)
        self.root.configure(menu=menu)

    def _build_status_bar(self) -> None:
        bar = ttk.Frame(self.root, padding=(PAD, SMALL_PAD))
        bar.pack(side="bottom", fill="x")
        self.status_var = tk.StringVar(value="「ファイルを選ぶ…」で計測データを読み込んでください。")
        ttk.Label(bar, textvariable=self.status_var).pack(side="left", fill="x", expand=True)
        self.progress = ttk.Progressbar(bar, length=260, maximum=1.0, mode="determinate")
        self.progress.pack(side="left", padx=PAD)
        self.cancel_button = ttk.Button(bar, text="中止", command=self.cancel_task, state="disabled")
        self.cancel_button.pack(side="left")

    def _font_changed(self) -> None:
        apply_font_size(self.root, self.font_size.get())

    # ------------------------------------------------------------------ 時間のかかる処理
    def run_task(self, message: str, function, on_done) -> None:
        if self.task is not None:
            messagebox.showinfo("処理中です", "前の処理が終わるまでお待ちください（「中止」で止められます）。", parent=self.root)
            return
        self.on_done = on_done
        self.set_status(message)
        self.progress.configure(value=0.0)
        self.task = BackgroundTask(function)
        self._set_busy(True)
        self.root.after(POLL_MS, self._poll)

    def _poll(self) -> None:
        task = self.task
        if task is None:
            return
        finished = None
        try:
            while True:
                kind, payload = task.queue.get_nowait()
                if kind == "progress":
                    fraction, message = payload
                    self.progress.configure(value=fraction)
                    self.set_status(message)
                else:
                    finished = (kind, payload)
                    break
        except queue.Empty:
            pass
        if finished is None:
            self.root.after(POLL_MS, self._poll)
            return
        self.task = None
        self._set_busy(False)
        kind, payload = finished
        self.progress.configure(value=1.0 if kind == "done" else 0.0)
        if kind == "done":
            callback, self.on_done = self.on_done, None
            try:
                callback(payload)
            except Exception as error:
                show_error(self.root, error)
        elif kind == "cancelled":
            self.set_status("中止しました。")
        else:
            self.set_status("問題が起きたため、処理を止めました。")
            show_error(self.root, payload)
        for listener in list(self.task_listeners):
            listener(kind)

    def cancel_task(self) -> None:
        if self.task is not None:
            self.task.cancel.set()
            self.set_status("中止しています…（区切りのよいところで止まります）")

    def _set_busy(self, busy: bool) -> None:
        self.cancel_button.state(["!disabled"] if busy else ["disabled"])
        for tab in (self.data_tab, self.settings_tab, self.results_tab):
            tab.set_busy(busy)

    def set_status(self, message: str) -> None:
        self.status_var.set(message)

    # ------------------------------------------------------------------ 状態の受け渡し
    def set_table(self, table, path: str, sheet: str | None) -> None:
        self.table = table
        self.settings.data.file_path = path
        self.settings.data.sheet = sheet
        self.invalidate_prepared()

    def invalidate_prepared(self) -> None:
        self.prepared = None
        self.notebook.tab(TAB_SETTINGS, state="disabled")
        self.settings_tab.set_busy(self.task is not None)
        self.settings_tab.update_preview()

    def set_prepared(self, prepared, options) -> None:
        self.prepared = prepared
        self.settings.data = options
        self.notebook.tab(TAB_SETTINGS, state="normal")
        self.settings_tab.set_busy(False)
        self.settings_tab.update_preview()
        self.set_status("データを確認しました。「2. 設定」で設定を確かめて「検証を実行」を押してください。")

    def set_result(self, result) -> None:
        self.result = result
        self.notebook.tab(TAB_RESULTS, state="normal")
        self.results_tab.show(result)
        self.select_tab(TAB_RESULTS)
        seconds = sum(result.elapsed_seconds.values())
        self.set_status(f"検証が終わりました（{seconds:.0f} 秒）。結果を確かめて「結果を保存…」で保存できます。")

    def select_tab(self, index: int) -> None:
        if self.notebook.tab(index, "state") != "disabled":
            self.notebook.select(index)

    def notify_saved(self, folder: Path) -> None:
        if messagebox.askyesno("保存しました", f"結果を保存しました。\n{folder}\n\nフォルダを開きますか？", parent=self.root):
            open_folder(folder)

    # ------------------------------------------------------------------ メニュー
    def load_settings_file(self) -> None:
        path = filedialog.askopenfilename(parent=self.root, title="設定ファイルを選ぶ", filetypes=[("設定（JSON）", "*.json")])
        if not path:
            return
        try:
            settings = load_settings(path)
        except Exception as error:
            show_error(self.root, UserFacingError("設定ファイルを読み込めません。", f"ファイルの中身が想定の形ではありません（{type(error).__name__}）。",
                                                  "このアプリの「設定を保存…」で作ったファイルを選んでください。"))
            return
        self.settings = settings
        self.data_tab.apply_options(settings.data)
        self.settings_tab.apply_settings(settings)
        message = "設定を読み込みました。"
        if self.table is None and settings.data.file_path and Path(settings.data.file_path).exists():
            if messagebox.askyesno("データも読み込みますか", f"設定に記録されたデータのファイルがあります。\n{settings.data.file_path}\n\n読み込みますか？", parent=self.root):
                self.data_tab.load_path(settings.data.file_path, settings.data.sheet)
        self.set_status(message)

    def save_settings_file(self) -> None:
        path = filedialog.asksaveasfilename(parent=self.root, title="設定を保存する", defaultextension=".json", filetypes=[("設定（JSON）", "*.json")],
                                            initialfile="検証の設定.json")
        if not path:
            return
        try:
            settings = self.settings_tab.collect_settings()
            save_settings(settings, path)
        except Exception as error:
            show_error(self.root, error)
            return
        self.set_status(f"設定を保存しました：{path}")

    def show_help(self) -> None:
        window = tk.Toplevel(self.root)
        use_light_appearance(window)
        window.title("使い方")
        window.geometry("900x640")
        text = text_box(window, height=30)
        scrollbar = ttk.Scrollbar(window, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        set_text(text, HELP_TEXT)
        scrollbar.pack(side="right", fill="y")
        text.pack(fill="both", expand=True)
        ttk.Button(window, text="閉じる", command=window.destroy).pack(pady=PAD)
        window.bind("<Escape>", lambda _e: window.destroy())

    def show_about(self) -> None:
        messagebox.showinfo(
            "このアプリについて",
            f"{APP_NAME} {APP_VERSION}\n\n"
            "Alignment・Overlay の Wafer 面内傾向の異常検知手法（M3S・係数SPC・Mahalanobis・PCA・GPR・EWMA・CUSUM・OR 統合）を、"
            "実データで同じ誤報率にそろえて比べます。計算の中身は、模擬データの検証（wafer_anomaly_monitoring）と同じコードです。\n\n"
            "データはこのパソコンの中だけで処理し、外部には送りません。",
            parent=self.root,
        )

    def open_log_folder(self) -> None:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        open_folder(LOG_PATH.parent)

    def make_sample_dialog(self) -> None:
        SampleDialog(self)

    def quit(self) -> None:
        if self.task is not None and not messagebox.askyesno("終了しますか", "計算の途中です。終了すると、計算中の結果は失われます。終了しますか？", parent=self.root):
            return
        if self.task is not None:
            self.task.cancel.set()
        self.root.destroy()


class SampleDialog:
    """練習用の模擬データ（実データではない）を作る小さな画面。"""

    def __init__(self, app: App):
        from ..sample_data import DEFAULT_LOTS, WAFERS_PER_LOT

        self.app = app
        self.window = tk.Toplevel(app.root)
        use_light_appearance(self.window)
        self.window.title("練習用の模擬データを作る")
        self.window.transient(app.root)
        body = ttk.Frame(self.window, padding=PAD * 2)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="検証と同じ作り方の模擬データです（実データではありません）。\n後半に、1 Wafer の異常4枚と、ゆっくり増える局所変形を入れてあります。",
                  justify="left").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, PAD))
        self.kind_var = tk.StringVar(value="csv")
        kinds = ttk.Frame(body)
        ttk.Radiobutton(kinds, text="CSV（速い）", value="csv", variable=self.kind_var).pack(side="left")
        ttk.Radiobutton(kinds, text="Excel（.xlsx。大きいと時間がかかります）", value="xlsx", variable=self.kind_var).pack(side="left", padx=PAD)
        labeled_row(body, 1, "形式", kinds)
        self.lots_var = tk.StringVar(value=str(DEFAULT_LOTS))
        labeled_row(body, 2, "Lot の数", ttk.Spinbox(body, from_=4, to=200, textvariable=self.lots_var, width=6), f"1 Lot = {WAFERS_PER_LOT} 枚")
        self.folder_var = tk.StringVar(value=str(Path.home() / "Documents"))
        folder = ttk.Frame(body)
        ttk.Entry(folder, textvariable=self.folder_var, width=44).pack(side="left")
        ttk.Button(folder, text="選ぶ…", command=self._choose).pack(side="left", padx=SMALL_PAD)
        labeled_row(body, 3, "保存先のフォルダ", folder)
        buttons = ttk.Frame(body)
        buttons.grid(row=8, column=0, columnspan=3, sticky="e", pady=(PAD, 0))
        ttk.Button(buttons, text="キャンセル", command=self.window.destroy).pack(side="right")
        ttk.Button(buttons, text="作る", style="Primary.TButton", command=self._make).pack(side="right", padx=PAD)
        self.window.bind("<Escape>", lambda _e: self.window.destroy())

    def _choose(self) -> None:
        folder = filedialog.askdirectory(parent=self.window, title="保存先のフォルダを選ぶ")
        if folder:
            self.folder_var.set(folder)

    def _make(self) -> None:
        from ..sample_data import write_sample

        try:
            lots = read_int(self.lots_var, "Lot の数")
            if not 4 <= lots <= 200:
                raise UserFacingError("Lot の数は 4〜200 にしてください。", f"「{lots}」は範囲の外です。", "4〜200 の整数を入れてください。")
        except Exception as error:
            show_error(self.window, error)
            return
        folder, kind = self.folder_var.get(), self.kind_var.get()
        self.window.destroy()

        def work(progress, cancel):
            progress(0.1, "練習用の模擬データを作っています")
            return write_sample(folder, kind, lots)

        self.app.run_task("練習用の模擬データを作っています", work, self._made)

    def _made(self, paths) -> None:
        self.app.set_status(f"練習用データを作りました：{paths[0]}")
        if messagebox.askyesno("作りました", f"練習用データを作りました。\n{paths[0]}\n（入れた異常の一覧：{paths[1].name}）\n\n今すぐ読み込みますか？", parent=self.app.root):
            self.app.data_tab.load_path(str(paths[0]))


def open_folder(folder: Path) -> None:
    import os
    import subprocess

    try:
        if sys.platform == "win32":
            os.startfile(folder)  # noqa: S606（エクスプローラーで開く）
        elif sys.platform == "darwin":
            subprocess.run(["open", str(folder)], check=False)
        else:
            webbrowser.open(folder.as_uri())
    except OSError:
        pass


# ---------------------------------------------------------------------- 自己診断
def quick_settings(table) -> AppSettings:
    """自己診断用の小さな設定（時間を短くするため、回数と系列を減らす）。"""
    from ..columns import auto_mapping
    from ..sample_data import LABEL_COLUMN

    settings = AppSettings()
    settings.data.mapping = auto_mapping(table.columns)
    settings.data.label_column = LABEL_COLUMN
    settings.data.label_abnormal_values = ["1"]
    settings.methods.alpha_percent = 5.0
    settings.temporal.target_arl0 = 100
    settings.temporal.n_bootstrap_series = 60
    settings.injection.single_replicates = 100
    settings.injection.temporal_series = 30
    settings.injection.temporal_components = ["low", "local"]
    settings.injection.temporal_amplitudes = [1.0]
    return settings


def run_self_test(output: str | Path) -> int:
    """画面を出さずに、練習用データで CSV と Excel の読み込み → 検証 → 保存 までを試す。"""
    from ..analysis import run_analysis
    from ..export import export_results
    from ..loader import read_table
    from ..preprocess import prepare
    from ..sample_data import write_sample

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    report = output / "self_test_result.txt"
    try:
        excel = write_sample(output / "sample_excel", "xlsx", SELF_TEST_EXCEL_LOTS)
        excel_table = read_table(excel[0])
        csv_paths = write_sample(output / "sample_csv", "csv", SELF_TEST_LOTS)
        table = read_table(csv_paths[0])
        settings = quick_settings(table)
        settings.data.file_path = str(csv_paths[0])
        prepared = prepare(table, settings.data)
        plots.configure_fonts()
        result = run_analysis(prepared, settings)
        folder = export_results(result, output, csv_paths[0].name)
        report.write_text(
            f"OK\nExcel {len(excel_table)} 行・CSV {len(table)} 行・計測 {prepared.check.n_measurements} 件\n保存先 {folder}\n", encoding="utf-8"
        )
        return 0
    except Exception:
        report.write_text("NG\n" + traceback.format_exc(), encoding="utf-8")
        return 1


class SmokeTest:
    """画面の部品を通して 読み込み → 確認 → 検証 → 結果の表示 → 保存 を行い、終わったら閉じる。"""

    def __init__(self, app: App, output: Path):
        self.app = app
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.report = self.output / "gui_smoke_test_result.txt"
        self.steps = [self.load, self.check, self.run, self.visit_results, self.save, self.finish]
        self.app.task_listeners.append(self.after_task)
        self.app.root.after(SMOKE_TEST_TIMEOUT_S * 1000, lambda: self.fail("時間切れ"))
        self.app.root.after(500, self.next)
        self.waiting = False
        self.ok = None

    def next(self) -> None:
        if self.ok is not None or not self.steps:
            return
        step = self.steps.pop(0)
        try:
            self.waiting = step() is True
        except Exception:
            self.fail(traceback.format_exc())
            return
        if not self.waiting:
            self.app.root.after(300, self.next)

    def after_task(self, kind: str) -> None:
        if self.ok is not None:
            return
        if kind != "done":
            self.fail(f"処理が {kind} で終わりました")
            return
        if self.waiting:
            self.waiting = False
            self.app.root.after(300, self.next)

    def load(self):
        from ..sample_data import write_sample

        paths = write_sample(self.output / "sample", "csv", SELF_TEST_LOTS)
        self.app.data_tab.load_path(str(paths[0]))
        return True

    def check(self):
        self.app.data_tab.check_data()
        return True

    def run(self):
        quick = quick_settings(self.app.table)
        quick.data = self.app.settings.data
        self.app.settings_tab.apply_settings(quick)
        self.app.settings_tab.run()
        return True

    def visit_results(self):
        tab = self.app.results_tab
        for page in tab.pages.values():
            if tab.notebook.tab(page, "state") != "hidden":
                tab.notebook.select(page)
                self.app.root.update()
        tab.only_alarm_var.set(True)
        tab.fill_table()
        tab._step_map(1)
        self.app.root.update()
        return False

    def save(self):
        from ..export import export_results

        result = self.app.result

        def work(progress, cancel):
            return export_results(result, self.output, "smoke", progress)

        self.app.run_task("結果を保存しています", work, lambda folder: None)
        return True

    def finish(self):
        self.ok = True
        self.report.write_text("OK\n", encoding="utf-8")
        self.app.root.after(200, self.app.root.destroy)
        return False

    def fail(self, message: str) -> None:
        if self.ok is not None:
            return
        self.ok = False
        self.report.write_text("NG\n" + message, encoding="utf-8")
        self.app.root.after(200, self.app.root.destroy)


def enable_windows_dpi_awareness() -> None:
    """Windows の表示倍率（125%・150% など）で文字がぼやけないようにする。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--self-test", metavar="出力先", help="画面を出さずに自己診断をする")
    parser.add_argument("--gui-smoke-test", metavar="出力先", help="画面の部品を通した自己診断をする")
    args = parser.parse_args(argv)
    if args.self_test:
        return run_self_test(args.self_test)
    enable_windows_dpi_awareness()
    root = tk.Tk()
    app = App(root)
    smoke = SmokeTest(app, Path(args.gui_smoke_test)) if args.gui_smoke_test else None
    root.mainloop()
    if smoke is not None:
        return 0 if smoke.ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
