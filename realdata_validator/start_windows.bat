@echo off
chcp 65001 > nul
setlocal
rem Windows で検証アプリを起動する（ダブルクリックで動く）。
rem 初回だけ、このフォルダに専用の Python 環境（.venv）を作り、必要なライブラリを入れる（数分かかる）。
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" goto run

echo 初回の準備をしています（数分かかります）...
call :find_python
if not defined PYTHON_CMD goto nopython
%PYTHON_CMD% -m venv .venv || goto failed
".venv\Scripts\python.exe" -m pip install --upgrade pip || goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto failed

:run
start "" ".venv\Scripts\pythonw.exe" run_app.py
exit /b 0

:find_python
set "PYTHON_CMD="
py -3.14 -c "import sys" > nul 2>&1 && set "PYTHON_CMD=py -3.14"
if defined PYTHON_CMD exit /b 0
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 14) else 1)" > nul 2>&1 && set "PYTHON_CMD=python"
exit /b 0

:nopython
echo Python 3.14 が見つかりません。
echo python.org から Python 3.14 をインストールしてから、もう一度ダブルクリックしてください。
echo インストールの最初の画面で「Add python.exe to PATH」にチェックを入れてください。
pause
exit /b 1

:failed
echo 準備に失敗しました。インターネットにつながっているか確かめ、.venv フォルダを消してからもう一度試してください。
echo 会社のネットワークでライブラリを入れられないときは、実行ファイル版（README の「実行ファイル版」）を使ってください。
pause
exit /b 1
