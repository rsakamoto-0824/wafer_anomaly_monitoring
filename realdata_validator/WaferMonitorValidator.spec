# -*- mode: python ; coding: utf-8 -*-
# 実データ検証アプリを、Python がない PC でも動く実行ファイルにする設定（PyInstaller）。
# 使い方：このフォルダで  pyinstaller --noconfirm WaferMonitorValidator.spec
#   Windows → dist/WaferMonitorValidator/WaferMonitorValidator.exe（フォルダごと配る）
#   Mac     → dist/WaferMonitorValidator.app
# PyInstaller は作った OS 用の実行ファイルしか作れない（Windows 用は Windows で作る）。
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent  # リポジトリのフォルダ
APP_NAME = "WaferMonitorValidator"

analysis = Analysis(
    [str(ROOT / "realdata_validator" / "run_app.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "configs" / "default.yaml"), "configs")],  # 練習用データの工程モデル
    hiddenimports=["src.realdata.gui.app"],
    excludes=["seaborn", "pyarrow", "pytest", "IPython", "jupyter", "notebook", "PyQt5", "PyQt6", "PySide2", "PySide6"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,  # 黒い画面（コンソール）を出さない
    upx=False,  # 圧縮するとウイルス対策ソフトに誤検知されやすい
)
collected = COLLECT(exe, analysis.binaries, analysis.datas, name=APP_NAME, upx=False)
if sys.platform == "darwin":
    app = BUNDLE(
        collected,
        name=f"{APP_NAME}.app",
        bundle_identifier="local.wafer-monitor-validator",
        info_plist={"NSHighResolutionCapable": True, "CFBundleDisplayName": "Wafer 実データ検証"},
    )
