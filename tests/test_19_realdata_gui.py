"""実データ検証アプリ：画面の部品を通した一連の操作（読み込み → 確認 → 検証 → 結果の表示 → 保存）。

画面を出せない環境（ディスプレイのない Linux など）では飛ばす。
"""
from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter")


def test_gui_smoke(tmp_path):
    from src.realdata.gui.app import App, SmokeTest

    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"画面を出せない環境: {error}")
    app = App(root)
    smoke = SmokeTest(app, tmp_path)
    root.mainloop()
    assert smoke.ok, (tmp_path / "gui_smoke_test_result.txt").read_text(encoding="utf-8")
    assert any(path.name.startswith("検証結果_") for path in tmp_path.iterdir())
