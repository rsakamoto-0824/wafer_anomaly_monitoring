#!/bin/bash
# Mac 用の実行ファイル（dist/WaferMonitorValidator.app）を作る。
# 1. 作るための Python 環境（.venv-build）を用意する  2. テストを通す  3. PyInstaller で作る  4. できたアプリで自己診断する
cd "$(dirname "$0")" || exit 1
set -e

PYTHON=""
for candidate in python3.14 /opt/homebrew/bin/python3.14 /usr/local/bin/python3.14 /Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PYTHON="$candidate"
    break
  fi
done
if [ -z "$PYTHON" ]; then
  echo "Python 3.14 が見つかりません。python.org から Python 3.14 をインストールしてください。"
  exit 1
fi

if [ ! -x ".venv-build/bin/python" ]; then
  "$PYTHON" -m venv .venv-build
  .venv-build/bin/python -m pip install --upgrade pip
  .venv-build/bin/python -m pip install -r requirements-build.txt
fi

echo "テストを実行しています..."
(cd .. && realdata_validator/.venv-build/bin/python -m pytest -q tests/test_17_realdata_input.py tests/test_18_realdata_analysis.py)

echo "実行ファイルを作っています（数分かかります）..."
.venv-build/bin/python -m PyInstaller --noconfirm --clean WaferMonitorValidator.spec

echo "できたアプリで自己診断をしています..."
CHECK_DIR="$(mktemp -d)"
dist/WaferMonitorValidator.app/Contents/MacOS/WaferMonitorValidator --self-test "$CHECK_DIR"
cat "$CHECK_DIR/self_test_result.txt"
rm -rf "$CHECK_DIR"
echo "できました：$(pwd)/dist/WaferMonitorValidator.app"
