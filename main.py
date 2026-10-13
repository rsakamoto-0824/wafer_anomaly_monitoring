"""コマンドラインから一括実行する入口。

例：
    .venv/bin/python main.py --config configs/quick_test.yaml            # 動作確認（数分）
    .venv/bin/python main.py --config configs/default.yaml --workers 6   # 本報告の計算
    .venv/bin/python main.py --config configs/default.yaml --stage figures report
段階：phase1 → phase2 → phase3 → apc → figures → report（all は全部を順に）。
Phase 2・3 は Phase 1 の結果（手法の順位）、Phase 3 は Phase 2 の結果を使う。
"""
from __future__ import annotations

import argparse
import time

from src.config import load_config

STAGES = ("phase1", "phase2", "phase3", "apc", "figures", "report")


def main() -> None:
    parser = argparse.ArgumentParser(description="Alignment・Overlay の Wafer 面内傾向の異常検知・経時変化監視の比較検証")
    parser.add_argument("--config", default="configs/default.yaml", help="設定ファイル（YAML）")
    parser.add_argument("--stage", nargs="+", default=["all"], choices=STAGES + ("all",), help="実行する段階")
    parser.add_argument("--workers", type=int, default=None, help="並列プロセス数（設定ファイルの workers を上書き）")
    parser.add_argument("--force", action="store_true", help="Phase 1 の途中結果（異常のスコア）を作り直す")
    args = parser.parse_args()
    config = load_config(args.config)
    stages = STAGES if "all" in args.stage else tuple(s for s in STAGES if s in args.stage)
    start = time.time()
    for stage in stages:
        print(f"===== {stage} =====", flush=True)
        if stage == "phase1":
            from src.experiments import phase1

            phase1.run(config, workers=args.workers, force=args.force)
        elif stage == "phase2":
            from src.experiments import phase2

            phase2.run(config, workers=args.workers)
        elif stage == "phase3":
            from src.experiments import phase3

            phase3.run(config, workers=args.workers)
        elif stage == "apc":
            from src.experiments import apc

            apc.run(config, workers=args.workers)
        elif stage == "figures":
            from src import visualization

            for path in visualization.make_all(config):
                print(path)
        elif stage == "report":
            from src import reporting

            print(reporting.build_report(config))
    print(f"全体 {time.time() - start:.0f} 秒", flush=True)


if __name__ == "__main__":
    main()
