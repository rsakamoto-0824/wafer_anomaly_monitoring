"""品質保証15：レポート中の数値と集計 CSV の数値が一致する。"""
import re

import numpy as np
import pandas as pd
import pytest

from src.config import load_config, output_dir
from src.reporting import MISSING_MARK, REPORT, ValueSpec, evaluate, format_value

CONFIG = load_config("configs/default.yaml")
METRICS = output_dir(CONFIG) / "metrics"


@pytest.fixture(scope="module")
def report_and_values():
    if not REPORT.exists() or not (METRICS / "report_values.csv").exists():
        pytest.skip("レポートがまだ作られていない（main.py --stage report）")
    return REPORT.read_text(encoding="utf-8"), pd.read_csv(METRICS / "report_values.csv", keep_default_na=False)


def test_every_embedded_value_matches_csv(report_and_values):
    report, values = report_and_values
    assert len(values) > 10
    for _, row in values.iterrows():
        spec = ValueSpec(row["key"], row["table"], row["query"], row["column"], row["agg"], row["fmt"])
        raw = evaluate(spec, METRICS)
        assert np.isclose(raw, float(row["raw"]), rtol=1e-9, atol=1e-12), row["key"]
        text = format_value(spec, raw)
        assert text == str(row["text"]), row["key"]
        assert text in report, f"{row['key']} の値 {text} がレポートにない"


def test_no_unfilled_placeholders(report_and_values):
    report, _ = report_and_values
    assert not re.search(r"\{\{[^}]+\}\}", report)
    assert MISSING_MARK not in report  # 本報告では全ての値・表を計算している


def test_tables_follow_csv(report_and_values):
    report, _ = report_and_values
    ranking = pd.read_csv(METRICS / "phase2_ranking.csv")
    first = ranking.iloc[0]
    name = first["detector"].replace("|", "\\|")
    assert f"| 1 | {name} | {first['mean_rmst_delay']:.2f} |" in report
    reps = pd.read_csv(METRICS / "phase1_representatives.csv")
    for _, row in reps.iterrows():
        assert f"{row['mean_detection']:.2f}" in report
