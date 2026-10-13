# wafer_anomaly_monitoring

半導体リソグラフィー工程の Alignment・Overlay 計測について、**Wafer 面内傾向の異常検知・経時変化監視の手法**を、
従来の M3S（|平均| + 3σ）管理と比べるシミュレーションです（Python）。

- 技術レポート（日本語 Markdown）：[reports/technical_report.md](reports/technical_report.md)
- 設計メモ（指定と、自分で決めた解釈・仮定）：[design.md](design.md)
- 課題・確認事項：[issues.md](issues.md)
- 参考文献の一覧：[references/references.json](references/references.json)

数値はすべて乱数で作った模擬データによります。実データ・社内データは使っていません。

## 結果の要点（誤報率をそろえた比較。数値の出典は `results/metrics/report_values.csv`）

| 問い | 答え（本報告の模擬データでの結果） |
|---|---|
| RQ1 M3S が見逃す形状異常に有効な手法 | M3S の検出率が 10% 未満の7種類で、計測値の PCA T²（寄与率 99%）が平均 52.0%（M3S 13.5%）。平均と標準偏差が同じ形の変化（B10）は M3S では 1.7%（誤報と同じ）、Mahalanobis（4次）は 8σ_dir で 90.4% |
| RQ2 経時変化を最も早く検知する手法 | 計測値の EWMA（λ = 0.05）＋ PCA T²（MEWMA）が平均 RMST 95.7 枚、Mahalanobis の MEWMA 100.0 枚（M3S 117.4 枚）。局所変化は PCA SPE の EWMA（28.5 枚）、Radial は M3S の CUSUM（71.5 枚）。正常工程の相関が強い（ρ = 0.95）と EWMA の利点は小さい（105.7 枚 対 Shewhart 110.3 枚） |
| RQ3 異常の種類による違い | 大きい。滑らかで正常な変動と同じ向き＝M3S、係数の組み合わせ＝Mahalanobis、局所・単一 Shot・高次＝PCA T²・SPE・GPR 残差 |
| RQ4 計測点数・ノイズの影響 | 単一 Shot の異常（PCA T²）は 0.82 → 25% の点で 0.18、ノイズ3倍で 0.52。低次の異常はほぼ不変。同じ点数での配置の差は最大 0.09。寄与率で決める PCA の主成分数はノイズで 66〜557 個と変わる |
| RQ5 APC 後の Overlay だけを見ると | 補正で除去できる異常（線形、3次以上の補正での3次の歪み）とそのドリフトを見逃す（検出率 0.6〜1.1% ＝誤報並み）。補正係数・補正前 Alignment の監視が必要。点の少ない Alignment に高次補正をすると残差 RMS が 5.27 → 10.21 nm |
| RQ6 単一手法で十分か | 不十分。M3S・Mahalanobis・PCA T²・SPE・GPR 残差の OR 統合が平均検出率 56.7%（単独の最良 49.9%）。経時変化は MEWMA と SPE の EWMA、APC 下は補正係数と残差を併用 |

### 規模と縮小した部分

- 仕様どおりの規模で実行：Phase 1（8手法 × 10パターン × 5振幅 × 1,000 回、FPR 5%・1%・0.1%）、Phase 2 本評価（上位の土台 × 4パターン × 6成分 × 5変化量 × 1,000 系列 × 300 枚）、Phase 3 の1 Wafer の部分（各条件 1,000 回）、APC の1 Wafer の部分（各条件 1,000 回）。
- 縮小して実行：Phase 2 の ρ の比較（A1・A2 × 低次・局所、500 系列）、Phase 3 の経時変化（A1・A2 × 低次・局所 × 0.5〜2σ_dir、300 系列）、APC の経時変化（A2 × 3成分 × 3変化量、300 系列）。
- `configs/full_experiment.yaml`（これらを全条件・1,000 系列にし、校正データも増やす設定）は**未実行**です。

## 比べたもの

| 区分 | 内容 |
|---|---|
| 監視手法 | M1 M3S、M2 多項式係数 SPC（3〜5次）、M3 Mahalanobis 距離、M4 PCA T²、M5 PCA SPE（寄与率 90・95・99%）、M6 GPR 残差（RBF・Matérn）、M7 EWMA（λ = 0.05〜0.4）、M8 CUSUM、と OR 統合 |
| 1 Wafer の異常（Phase 1） | B1〜B10（Radial・Tangential・局所・非対称・高次・係数の組み合わせ・表現できない高次・Scan 依存・単一 Shot・平均と分散が同じ） × 1〜16σ_dir × 1,000 回、FPR 5%・1%・0.1% |
| 経時変化（Phase 2） | A1 Step・A2 Ramp・A3 非線形 Drift・A4 周期 × 6成分 × 0.25〜3σ_dir × 1,000 系列（300 枚）、ARL₀ = 370、ρ = 0〜0.95 |
| 計測条件（Phase 3） | 計測密度（全点・50%・25%）、計測配置（実計測風・均等・D 最適・I 最適）、計測ノイズ（0.5〜3倍）、監視多項式の次数（3〜5次） |
| APC（検証D） | 補正次数 1・3・5 次、補正前 Alignment・補正係数・補正後 Overlay 残差のどれを監視するか |

## 必要な環境

- Python 3.14.5 以上（動作確認は Python 3.14.6、macOS・Apple M1・メモリ 8 GB）
- ライブラリ（版は [requirements.txt](requirements.txt) で固定）：NumPy、SciPy、pandas、scikit-learn、Matplotlib、seaborn、PyYAML、pytest、pyarrow（Parquet の書き出し）、joblib（並列処理）
- 環境変数・認証情報・外部 API は使いません。

## 環境構築

```bash
python3.14 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

## 実行方法

ユニットテスト（品質保証の15項目を59件のテストで確認、約10秒）：

```bash
.venv/bin/python -m pytest
```

動作確認（小さな設定で全工程。約5分。結果は `results_quick/`、精度が低いので報告には使わない。レポートは `results_quick/technical_report.md` に作られ、この設定で計算しない値は「（未計算）」になる）：

```bash
.venv/bin/python main.py --config configs/quick_test.yaml --workers 2
```

本報告の計算（`results/` に出力）：

```bash
.venv/bin/python main.py --config configs/default.yaml --workers 6
```

段階を選んで実行することもできます（`phase1`・`phase2`・`phase3`・`apc`・`figures`・`report`）。Phase 2・3 は Phase 1 の順位、Phase 3 は Phase 2 の順位を使います：

```bash
.venv/bin/python main.py --config configs/default.yaml --stage figures report
```

途中結果は `results/cache/` に保存し、再実行すると再利用します（Phase 1 の正常データのスコアなど）。作り直すときは `--force` を付けるか、フォルダを消します。

計算時間の目安（M1・8 コア・メモリ 8 GB・6 並列）：Phase 1 約4分、Phase 2 約50分、Phase 3 約10分、APC 約4分、図とレポート 約20秒。

### フルスケール評価

`configs/full_experiment.yaml` は、本報告の設定より大きな評価（誤報率 0.1% の精度を上げる校正データの増量、Phase 2 の ρ 比較を全条件で行うなど）の設定です。

```bash
.venv/bin/python main.py --config configs/full_experiment.yaml --workers 6
```

## 出力

| フォルダ | 内容 |
|---|---|
| `results/metrics/` | 集計表（CSV と Parquet の両方）。phase1_*（1 Wafer）、phase2_*（経時変化）、phase3_*（計測条件）、apc_*（APC）、report_values.csv（レポートに埋め込んだ値と出典） |
| `results/figures/` | Figure 1〜10 と付録の図（PNG と PDF） |
| `results/samples/` | 図に使った代表例（npz） |
| `reports/technical_report.md` | 技術レポート（`reports/technical_report_template.md` に数値と表を埋め込んで作る） |

## フォルダ構成

```text
wafer_anomaly_monitoring/
├── main.py                 # 一括実行の入口
├── configs/                # default.yaml（本報告）・quick_test.yaml（動作確認）・full_experiment.yaml
├── src/
│   ├── wafer_geometry.py   # Wafer・Shot・Mark の座標
│   ├── zernike.py          # Zernike 多項式（Fringe 番号、RMS 正規化）
│   ├── simulation.py       # 正常な面内傾向と計測値の生成
│   ├── temporal_process.py # AR(1) の時系列と経時変化の時間プロファイル
│   ├── anomaly_generator.py# 異常パターン B1〜B10・経時変化の成分・B10 の作り方
│   ├── sampling.py         # 計測マップ（間引き・実計測風・均等・D 最適・I 最適）
│   ├── feature_extraction.py # 多項式係数・M3S
│   ├── monitoring/         # M1〜M8（m3s・polynomial_spc・mahalanobis・pca_monitor・gpr_monitor・ewma・cusum）
│   ├── calibration.py      # 管理限界の校正（FPR・OR 統合・ARL₀）
│   ├── evaluation.py       # 検出率・AUC・検出遅延と信頼区間
│   ├── experiments/        # phase1・phase2・phase3・apc の実行
│   ├── visualization.py    # 図
│   └── reporting.py        # レポートへの数値・表の埋め込み
├── tests/                  # 品質保証の15項目
├── results/                # metrics・figures・samples（cache は Git に入れない）
└── reports/                # 技術レポート
```

## 注意事項

- 正常工程・計測誤差・異常の大きさなどの数値は仮定です（design.md・issues.md）。実工程に当てはめる前に、実データで正常モデルを学習し直してください。
- 管理限界は正常データから経験的に決めています。理論式だけの限界は大きくずれることがあります（レポート第4.9節）。
