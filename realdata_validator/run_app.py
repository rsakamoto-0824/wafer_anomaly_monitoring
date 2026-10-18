"""検証アプリを起動する（start_mac.command・start_windows.bat と、実行ファイル化（PyInstaller）の入口）。

起動に失敗したときも黙って終わらないように、理由をログに書き、画面に知らせる
（Windows ではコンソールなしで起動するので、エラーの文字が見えないため）。
"""
import multiprocessing
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MIN_PYTHON = (3, 14)
LOG_PATH = Path.home() / ".wafer_monitor_validator" / "log.txt"


def report_startup_error(message: str) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as file:
            file.write(message + "\n")
    except OSError:
        pass
    try:
        import tkinter
        from tkinter import messagebox

        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror("起動できません", message + f"\n\n詳しい内容はログ（{LOG_PATH}）にあります。")
        root.destroy()
    except Exception:  # 画面が出せないときは標準エラーに出す
        print(message, file=sys.stderr)


def start() -> int:
    if sys.version_info < MIN_PYTHON:
        report_startup_error(
            f"Python {sys.version.split()[0]} では動きません。\n理由：このアプリは Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} 以上向けに作っています。\n"
            "対処：python.org から Python 3.14 をインストールし、start_windows.bat（Mac は start_mac.command）で起動し直してください。"
        )
        return 1
    try:
        from src.realdata.gui.app import main
    except Exception:
        report_startup_error(
            "アプリの部品を読み込めませんでした。\n理由：必要なライブラリが入っていないか、フォルダの中身が欠けています。\n"
            "対処：realdata_validator フォルダの .venv を消してから、start_windows.bat（Mac は start_mac.command）で起動し直してください。\n\n"
            + traceback.format_exc()
        )
        return 1
    return main()


def keep_font_cache() -> None:
    """実行ファイル版では、図の書体の一覧（matplotlib のキャッシュ）を毎回作り直さないよう、ホームフォルダに置く。

    PyInstaller は既定で一時フォルダを使うので、起動のたびに数秒〜十数秒かかる。
    """
    if getattr(sys, "frozen", False):
        folder = LOG_PATH.parent / "matplotlib"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            os.environ["MPLCONFIGDIR"] = str(folder)
        except OSError:
            pass


if __name__ == "__main__":
    keep_font_cache()
    multiprocessing.freeze_support()  # 実行ファイル化したときに、裏で別のプロセスを起動しても二重に立ち上がらないように
    sys.exit(start())
