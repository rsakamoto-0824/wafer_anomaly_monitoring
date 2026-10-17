# 結果の説明資料（PowerPoint）の作り方

`../Wafer面内傾向の異常検知手法比較_説明資料.pptx`（31枚、ノート付き）を作るスクリプト一式です。
資料の数値はすべて `../../results/metrics/` の CSV（技術レポートと同じ計算結果）から自動で取り出しており、手で書き写していません。

## ファイル

| ファイル | 役割 |
| --- | --- |
| `prepare_data.py` | 計算結果の CSV から、資料に載せる数値を `deck_data.json` に書き出す |
| `render_formulas.py` | 数式を画像にする（`formulas/`、Git には入れない） |
| `build_deck.js` | 色・文字・図形の共通設定と補助関数。`slides.js` を呼んで PPTX を書き出す |
| `slides.js` | 31枚のスライドの中身とノート |
| `postprocess.py` | 日本語フォントの指定、グラフの空欄の点の削除、ファイルの圧縮などの後処理 |

## 実行方法

リポジトリ直下の `.venv`（Python）と、グローバルに入っている `pptxgenjs`（Node.js）を使います。このフォルダで次の順に実行します。

```bash
../../.venv/bin/python prepare_data.py
../../.venv/bin/python render_formulas.py
NODE_PATH="$(npm root -g)" node build_deck.js deck_raw.pptx
../../.venv/bin/python postprocess.py deck_raw.pptx deck.building.pptx
cp deck.building.pptx "../Wafer面内傾向の異常検知手法比較_説明資料.pptx"
```

`deck_raw.pptx`・`deck.building.pptx`・`formulas/` は途中で作られるファイルなので、Git には入れません。

## 注意事項

- 計算をやり直したときは、先に図とレポートを作り直してから、上の手順を最初から実行します。
- グラフは PowerPoint の標準のグラフ（データ付き）、計算結果の図は `../../results/figures/` の画像を貼っています。
- 8枚目のグラフの横軸は、PowerPoint では 50 枚ごとに目盛りの数字を間引いています（間引かないと数字が縦に折り返す）。
- 資料の数値は模擬データによるシミュレーションの結果で、実データ・社内データは使っていません。
