@echo off
chcp 65001 > nul
setlocal
rem Windows 用の実行ファイル（dist\WaferMonitorValidator\WaferMonitorValidator.exe）を作る。
rem 1. 作るための Python 環境（.venv-build）を用意する  2. テストを通す  3. PyInstaller で作る  4. できたアプリで自己診断する
cd /d "%~dp0"
call :find_python
if not defined PYTHON_CMD goto nopython
if exist ".venv-build\Scripts\python.exe" goto test
%PYTHON_CMD% -m venv .venv-build || goto failed
".venv-build\Scripts\python.exe" -m pip install --upgrade pip || goto failed
".venv-build\Scripts\python.exe" -m pip install -r requirements-build.txt || goto failed

:test
echo テストを実行しています...
pushd ..
"realdata_validator\.venv-build\Scripts\python.exe" -m pytest -q tests\test_17_realdata_input.py tests\test_18_realdata_analysis.py
set "TEST_RESULT=%ERRORLEVEL%"
popd
if not "%TEST_RESULT%"=="0" goto failed

echo 実行ファイルを作っています（数分かかります）...
".venv-build\Scripts\python.exe" -m PyInstaller --noconfirm --clean WaferMonitorValidator.spec || goto failed

echo できたアプリで自己診断をしています...
set "CHECK_DIR=%TEMP%\wafer_validator_check"
if exist "%CHECK_DIR%" rmdir /s /q "%CHECK_DIR%"
start "" /wait "dist\WaferMonitorValidator\WaferMonitorValidator.exe" --self-test "%CHECK_DIR%"
type "%CHECK_DIR%\self_test_result.txt"
findstr /b "OK" "%CHECK_DIR%\self_test_result.txt" > nul || goto failed
echo できました：%~dp0dist\WaferMonitorValidator\WaferMonitorValidator.exe
echo dist\WaferMonitorValidator フォルダごと配ってください（exe だけでは動きません）。
if not defined CI pause
exit /b 0

:find_python
set "PYTHON_CMD="
py -3.14 -c "import sys" > nul 2>&1 && set "PYTHON_CMD=py -3.14"
if defined PYTHON_CMD exit /b 0
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 14) else 1)" > nul 2>&1 && set "PYTHON_CMD=python"
exit /b 0

:nopython
echo Python 3.14 が見つかりません。python.org から Python 3.14 をインストールしてください。
if not defined CI pause
exit /b 1

:failed
echo 途中で失敗しました。上に出ているメッセージを確かめてください。
if not defined CI pause
exit /b 1
