"""実データ（Excel・CSV の計測テーブル）で監視手法を比べる検証アプリの計算部分。

画面（gui/）からも、テストからも同じ関数を呼ぶ。計算部分は画面の部品を読み込まない。
- columns.py    ：計測テーブルの標準の項目名（Overlay計測ルール）と、列の自動対応づけ
- loader.py     ：CSV・Excel の読み込み
- preprocess.py ：前処理（未測定の除外、重複の平均、有効半径、時間の順番）
- dataset.py    ：共通の計測点、欠けた点の補完、学習・校正・評価への分割
- methods.py    ：監視手法（M1〜M6）の組み立て
- temporal.py   ：EWMA・CUSUM の管理限界（ARL₀）と実データでの判定
- injection.py  ：異常の注入試験（1 Wafer・経時変化）
- analysis.py   ：全体の流れ
- plots.py・export.py・sample_data.py：図、保存、練習用の模擬データ
"""
