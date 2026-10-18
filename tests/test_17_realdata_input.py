"""実データ検証アプリ：読み込み・前処理・共通の計測点と欠けの補完（Overlay計測ルールどおりか）。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.realdata.columns import COLUMN_NAMES, auto_mapping, missing_required
from src.realdata.dataset import SEGMENT_CALIBRATION, SEGMENT_EXCLUDED, SEGMENT_TRAIN, PPCAImputer, build_dataset
from src.realdata.errors import UserFacingError
from src.realdata.loader import read_table
from src.realdata.methods import ObservedM3SMonitor, nan_m3s_by_axis
from src.realdata.preprocess import default_abnormal_values, natural_key, prepare
from src.realdata.settings import DataOptions, SplitOptions


SHOTS_3 = [(0.0, 0.0), (26.0, 0.0), (-26.0, 33.0)]
SHOTS_6 = SHOTS_3 + [(0.0, 33.0), (26.0, 33.0), (-26.0, -33.0)]


def small_table(n_wafers: int = 3, shots=SHOTS_3) -> pd.DataFrame:
    """数 Shot × 2 Mark の小さな計測テーブル（標準の項目名）。"""
    rows = []
    marks = [(-5.0, -5.0), (5.0, 5.0)]
    for w in range(n_wafers):
        for shot_no, (sx, sy) in enumerate(shots, start=1):
            for mark_no, (mx, my) in enumerate(marks, start=1):
                rows.append(
                    {
                        "Wafer": f"LOT-{w + 1}",
                        "DateTime": "2026/9/1 8:00",
                        "shotNo": shot_no,
                        "Direction": 1 + shot_no % 2,
                        "Xmm": sx,
                        "Ymm": sy,
                        "Radius": float(np.hypot(sx, sy)),
                        "markNo": mark_no,
                        "markXmm": mx,
                        "markYmm": my,
                        "measX": 10.0 * (w + 1) + shot_no,
                        "measY": -1.0 * mark_no,
                        "StsX": 0,
                        "StsY": 0,
                    }
                )
    return pd.DataFrame(rows)


def options_for(table: pd.DataFrame, **changes) -> DataOptions:
    options = DataOptions(mapping=auto_mapping(table.columns))
    for key, value in changes.items():
        setattr(options, key, value)
    return options


def test_auto_mapping_exact_then_case_insensitive():
    mapping = auto_mapping(["wafer", "DateTime", "XMM", "Ymm", "markXmm", "markYmm", "measx", "measY", "other"])
    assert mapping["Wafer"] == "wafer" and mapping["Xmm"] == "XMM" and mapping["measX"] == "measx"
    assert mapping["StsX"] is None
    assert missing_required(mapping) == []
    assert set(mapping) == set(COLUMN_NAMES)


def test_read_csv_utf8_shift_jis_tab_and_excel(tmp_path):
    table = small_table().assign(備考="日本語")
    table.to_csv(tmp_path / "utf8.csv", index=False, encoding="utf-8-sig")
    table.to_csv(tmp_path / "sjis.csv", index=False, encoding="cp932")
    table.to_csv(tmp_path / "tab.tsv", index=False, sep="\t")
    table.to_excel(tmp_path / "book.xlsx", index=False)
    for name in ("utf8.csv", "sjis.csv", "tab.tsv", "book.xlsx"):
        loaded = read_table(tmp_path / name)
        assert list(loaded.columns) == list(table.columns), name
        assert len(loaded) == len(table)
        assert loaded["備考"].iloc[0] == "日本語"
    with pytest.raises(UserFacingError):
        (tmp_path / "old.xls").write_bytes(b"dummy")
        read_table(tmp_path / "old.xls")


def test_unmeasured_values_are_missing_not_zero():
    table = small_table()
    table.loc[0, ["StsX", "measX"]] = [-1, 0.0]  # 未測定の行に 0 が入っていても使わない
    table.loc[1, ["StsY", "measY"]] = [-1, 999.0]
    prepared = prepare(table, options_for(table))
    assert np.isnan(prepared.values[0, 0, 0])
    assert np.isnan(prepared.values[0, 1, 1])
    assert prepared.check.n_x_unmeasured == 1 and prepared.check.n_y_unmeasured == 1
    assert not np.isnan(prepared.values[0, 0, 1])  # Y は有効なので残る


def test_duplicates_are_averaged_per_axis():
    table = small_table()
    extra = table.iloc[[0]].copy()
    extra["measX"] = extra["measX"] + 2.0
    extra["measY"] = np.nan  # Y は空欄（欠測）なので平均に入れない
    prepared = prepare(pd.concat([table, extra], ignore_index=True), options_for(table))
    assert prepared.check.n_duplicate_groups == 1
    assert prepared.values[0, 0, 0] == pytest.approx(table.loc[0, "measX"] + 1.0)
    assert prepared.values[0, 0, 1] == pytest.approx(table.loc[0, "measY"])


def test_points_on_or_outside_valid_radius_are_excluded_and_radius_checked():
    table = small_table(1)
    edge = table.iloc[[0]].copy()
    edge[["Xmm", "Ymm", "markXmm", "markYmm"]] = [150.0, 0.0, 0.0, 0.0]  # r = 150 ちょうどは使わない
    edge["Radius"] = 140.0  # Xmm・Ymm からの計算値（150）と合わない
    prepared = prepare(pd.concat([table, edge], ignore_index=True), options_for(table))
    assert prepared.check.n_rows_outside_radius == 1
    assert prepared.check.n_radius_mismatch == 1
    assert prepared.points["r_mm"].max() < 150.0


def test_time_order_natural_sort_and_remeasurement():
    table = pd.concat([small_table(1).assign(Wafer=name) for name in ("L-10", "L-2", "L-1")], ignore_index=True)
    later = small_table(1).assign(Wafer="L-2", DateTime="2026/9/2 8:00")
    table = pd.concat([table, later], ignore_index=True)
    prepared = prepare(table, options_for(table))
    assert list(prepared.measurements["Wafer"]) == ["L-1", "L-2", "L-10", "L-2"]
    assert prepared.check.n_remeasured_wafers == 1
    last = prepare(table, options_for(table, remeasure_policy="last"))
    assert list(last.measurements["Wafer"]) == ["L-1", "L-10", "L-2"]
    assert natural_key("W-2") < natural_key("W-10")


def test_unit_filter_and_label():
    table = small_table().assign(Layer=["A", "B"] * 9, 判定=lambda t: np.where(t["Wafer"] == "LOT-2", "NG", "OK"))
    prepared = prepare(
        table,
        options_for(table, measurement_unit="um", filter_column="Layer", filter_values=["A"], label_column="判定", label_abnormal_values=["NG"]),
    )
    assert prepared.check.n_rows_filtered_out == 9
    assert np.nanmax(np.abs(prepared.values[..., 1])) == pytest.approx(1000.0)  # µm → nm（残るのは Mark 1 の行）
    assert list(prepared.measurements["label"]) == [False, True, False]
    assert default_abnormal_values(["0", "1", "OK", "NG", "異常", "2"]) == ["1", "NG", "異常", "2"]


def test_missing_required_column_message():
    table = small_table().drop(columns=["measY"])
    with pytest.raises(UserFacingError) as error:
        prepare(table, options_for(table))
    assert "measY" in error.value.what


def test_ppca_imputer_recovers_low_rank_values():
    rng = np.random.default_rng(0)
    latent = rng.standard_normal((300, 3)) @ rng.standard_normal((3, 40)) * 5.0
    values = latent + 0.05 * rng.standard_normal(latent.shape)
    observed = values.copy()
    missing = rng.random(values.shape) < 0.05
    observed[missing] = np.nan
    filled = PPCAImputer().fit(observed[:200]).transform(observed)
    error = np.abs(filled[missing] - values[missing])
    assert np.median(error) < 0.2  # 値の大きさ（標準偏差 約 9）に比べて十分小さい
    assert np.array_equal(filled[~missing], observed[~missing])


def test_observed_m3s_ignores_missing_points():
    values = np.array([[1.0, 2.0, np.nan, 4.0, 1.0, 1.0, 1.0, 1.0]])
    expected_x = abs(np.mean([1, 2, 4])) + 3 * np.std([1, 2, 4], ddof=1)
    assert nan_m3s_by_axis(values)[0, 0] == pytest.approx(expected_x)
    monitor = ObservedM3SMonitor().fit(np.vstack([values, values + 1, values * 2]))
    assert np.isfinite(monitor.score(values)).all()


def test_dataset_map_exclusion_and_split():
    rng = np.random.default_rng(1)
    table = pd.concat([small_table(1, SHOTS_6).assign(Wafer=f"W-{i:03d}") for i in range(80)], ignore_index=True)
    table["measX"] = rng.normal(0, 1, len(table))
    table["measY"] = rng.normal(0, 1, len(table))
    rare = table.iloc[[0]].assign(Xmm=60.0, Ymm=60.0)  # 1回しか計測されない点 → 共通の計測点に入れない
    sparse = table["Wafer"] == "W-070"
    table.loc[sparse & (table["shotNo"] > 3), "StsX"] = -1  # 12 点のうち 6 点の X が欠ける（25%）→ 除外
    table = pd.concat([table, rare], ignore_index=True)
    prepared = prepare(table, options_for(table))
    dataset = build_dataset(prepared, SplitOptions(normal_fraction_percent=60, train_fraction_percent=50, max_missing_percent=20), 150.0)
    assert dataset.n_points == 12
    segments = dataset.measurements.set_index("Wafer")["segment"]
    assert segments["W-070"] == SEGMENT_EXCLUDED
    assert (segments == SEGMENT_TRAIN).sum() == 24 and (segments == SEGMENT_CALIBRATION).sum() == 24
    assert not np.isnan(dataset.filled).any()
