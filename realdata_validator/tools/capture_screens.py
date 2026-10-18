"""開発用（Mac）：練習用の模擬データでアプリを動かし、各画面をアプリの窓の範囲だけ撮影する。

README の画面の画像（../docs/）を作り直すときに使う。撮影の間はアプリを最前面にして、ほかの窓が写らないようにする。
使い方：.venv/bin/python realdata_validator/tools/capture_screens.py 出力先フォルダ
"""
from __future__ import annotations

import subprocess
import sys
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.realdata.gui.app import App, SmokeTest, quick_settings  # noqa: E402

RESULT_PAGES = ("summary", "chart", "overview", "table", "map", "temporal", "label", "single", "drift")


class Capture(SmokeTest):
    """SmokeTest と同じ流れで、各画面を撮る（検証は既定に近い設定で行う）。"""

    def __init__(self, app: App, output: Path):
        super().__init__(app, output)
        self.steps = [self.load, self.shot_step("01_data_top"), self.check, self.scroll_shot(self.app.data_tab, 0.55, "02_data_bottom"),
                      self.go_settings, self.run]
        self.steps += [self.result_step(key) for key in RESULT_PAGES] + [self.finish]

    def shot(self, name: str) -> None:
        root = self.app.root
        root.attributes("-topmost", True)
        root.lift()
        root.update_idletasks()
        root.update()
        x, y, w, h = root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height()
        subprocess.run(["screencapture", "-x", "-R", f"{x},{y},{w},{h}", str(self.output / f"{name}.png")], check=False)

    def shot_step(self, name: str):
        def step():
            self.shot(name)
            return False
        return step

    def scroll_shot(self, tab, position: float, name: str):
        def step():
            canvas = tab.winfo_children()[0].canvas
            canvas.yview_moveto(position)
            self.shot(name)
            canvas.yview_moveto(0)
            return False
        return step

    def go_settings(self):
        self.app.select_tab(1)
        self.shot("03_settings_top")
        canvas = self.app.settings_tab.winfo_children()[0].canvas
        for number, position in enumerate((0.33, 0.66, 1.0), start=4):
            canvas.yview_moveto(position)
            self.shot(f"0{number}_settings_{number - 3}")
        canvas.yview_moveto(0)
        return False

    def run(self):
        settings = quick_settings(self.app.table)
        settings.data = self.app.data_tab.collect_options()
        settings.methods.alpha_percent = 1.0
        settings.temporal.target_arl0 = 370
        settings.temporal.n_bootstrap_series = 200
        settings.injection.single_replicates = 300
        settings.injection.temporal_series = 60
        settings.injection.temporal_components = ["low", "high", "radial", "local"]
        settings.injection.temporal_amplitudes = [0.5, 1.0, 2.0]
        self.app.settings_tab.apply_settings(settings)
        self.app.settings_tab.run()
        return True

    def result_step(self, key: str):
        def step():
            tab = self.app.results_tab
            page = tab.pages[key]
            if tab.notebook.tab(page, "state") == "hidden":
                return False
            tab.notebook.select(page)
            self.app.root.update()
            self.shot(f"1{RESULT_PAGES.index(key)}_result_{key}")
            return False
        return step


def main() -> int:
    output = Path(sys.argv[1])
    root = tk.Tk()
    app = App(root)
    capture = Capture(app, output)
    root.mainloop()
    return 0 if capture.ok else 1


if __name__ == "__main__":
    sys.exit(main())
