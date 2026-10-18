#!/bin/bash
# Mac で検証アプリを起動する（ダブルクリックで動く）。
# 初回だけ、このフォルダに専用の Python 環境（.venv）を作り、必要なライブラリを入れる（数分かかる）。
cd "$(dirname "$0")" || exit 1

PYTHON=""
for candidate in python3.14 /opt/homebrew/bin/python3.14 /usr/local/bin/python3.14 /Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PYTHON="$candidate"
    break
  fi
done

if [ ! -x ".venv/bin/python" ]; then
  if [ -z "$PYTHON" ]; then
    echo "Python 3.14 が見つかりません。python.org から Python 3.14 をインストールしてから、もう一度ダブルクリックしてください。"
    read -r -p "Enter キーで閉じます"
    exit 1
  fi
  echo "初回の準備をしています（数分かかります）..."
  "$PYTHON" -m venv .venv || { echo "Python 環境を作れませんでした。"; read -r -p "Enter キーで閉じます"; exit 1; }
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt || {
    echo "ライブラリを入れられませんでした。インターネットにつながっているか確かめて、.venv フォルダを消してからもう一度試してください。"
    read -r -p "Enter キーで閉じます"
    exit 1
  }
fi

.venv/bin/python run_app.py
