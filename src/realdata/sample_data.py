"""練習用の模擬データ（実データではない）を、計測テーブルの標準の形で作る。

正常の変動は検証と同じ作り方（configs/default.yaml の工程モデル、AR(1) の時系列、Shot・Mark の計測誤差）。
アプリの動きを確かめられるように、次のものを入れる。
- 後半に 1 Wafer の異常（局所変形・単一 Shot・高次・Radial）を4枚。列「既知の異常」を 1 にする
- 最後の約2割に、局所変形がゆっくり増える経時変化（Ramp。ラベルは付けない）
- 未測定（Sts = −1、計測値は 0）を 0.5%、重複行を 0.2%
入れた異常の一覧（答え合わせ用）も一緒に返す。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ..anomaly_generator import AnomalyGenerator, AnomalySettings
from ..config import load_config, make_rng
from ..simulation import MeasurementSystem, NoiseModel, build_process_model
from ..temporal_process import coefficient_sequence, temporal_profile
from ..wafer_geometry import build_layout

SAMPLE_SEED = 20261018
DEFAULT_LOTS = 24
WAFERS_PER_LOT = 25
LOT_INTERVAL_HOURS = 6
START_TIME = datetime(2026, 9, 1, 8, 0)
STATUS_MISSING_RATE = 0.005
DUPLICATE_RATE = 0.002
DUPLICATE_NOISE_NM = 0.1
LABEL_COLUMN = "既知の異常"
SINGLE_EVENTS = (  # （全体の何割の位置か, パターン, 大きさ σ_dir, 説明）
    (0.62, "B3", 8.0, "局所的な変形"),
    (0.66, "B9", 8.0, "単一 Shot の異常"),
    (0.70, "B5", 4.0, "高次の Zernike 成分"),
    (0.74, "B1", 4.0, "Radial 方向の異常"),
)
DRIFT_START_FRACTION = 0.80
DRIFT_COMPONENT = "local"
DRIFT_AMPLITUDE = 2.0  # Ramp が 100 枚で到達する大きさ（σ_dir）
DRIFT_RAMP_LENGTH = 100


def generate_sample_table(n_lots: int = DEFAULT_LOTS, seed: int = SAMPLE_SEED) -> tuple[pd.DataFrame, pd.DataFrame]:
    """（計測テーブル, 入れた異常の一覧）。"""
    if n_lots < 4:
        raise ValueError("練習用データは 4 Lot 以上にしてください")
    config = load_config("configs/default.yaml")
    layout = build_layout(config["wafer"], config["marks"])
    process = build_process_model(config["normal_process"])
    noise = NoiseModel.from_config(config["noise"])
    points = layout.points("alignment")
    system = MeasurementSystem(process, noise, points, layout.n_shots)
    generator = AnomalyGenerator(process, layout, system, AnomalySettings.from_config(config.get("anomaly", {})))
    rng = make_rng(seed, "sample_data")
    n_wafers = n_lots * WAFERS_PER_LOT
    values = system.measure(coefficient_sequence(process, rng, 1, n_wafers)[0], rng)

    events = []
    for fraction, pattern, amplitude, description in SINGLE_EVENTS:
        index = int(fraction * n_wafers)
        params = generator.draw(pattern, rng, 1)
        values[index] += amplitude * generator.unit_fields(pattern, params)[0]
        events.append({"order": index + 1, "kind": "1 Wafer", "pattern": pattern, "amplitude_sigma": amplitude, "description": description})
    onset = int(DRIFT_START_FRACTION * n_wafers) + 1
    profile = temporal_profile("A2", n_wafers, onset, {"ramp_length": DRIFT_RAMP_LENGTH})
    values += DRIFT_AMPLITUDE * profile[:, None] * generator.unit_fields(DRIFT_COMPONENT, {"n": 1})[0][None, :]
    events.append(
        {
            "order": onset,
            "kind": "経時変化",
            "pattern": f"A2（{DRIFT_COMPONENT}）",
            "amplitude_sigma": DRIFT_AMPLITUDE,
            "description": f"{onset} 枚目から局所変形が増える（{DRIFT_RAMP_LENGTH} 枚で {DRIFT_AMPLITUDE:g}σ_dir）",
        }
    )

    marks = layout.mark_table(points)
    n_points = len(points)
    lot = np.arange(n_wafers) // WAFERS_PER_LOT
    wafer_ids = np.array([f"SIM{l + 1:03d}-{w % WAFERS_PER_LOT + 1:02d}" for w, l in enumerate(lot)])
    times = np.array([START_TIME + timedelta(hours=LOT_INTERVAL_HOURS * int(l)) for l in lot])
    table = pd.DataFrame(
        {
            "Wafer": np.repeat(wafer_ids, n_points),
            "DateTime": np.repeat(times, n_points),
            "shotNo": np.tile(marks["shotNo"].to_numpy(), n_wafers),
            "Direction": np.tile(marks["Direction"].to_numpy(), n_wafers),
            "Xmm": np.tile(marks["Xmm"].round(3).to_numpy(), n_wafers),
            "Ymm": np.tile(marks["Ymm"].round(3).to_numpy(), n_wafers),
            "Radius": np.tile(marks["Radius"].round(4).to_numpy(), n_wafers),
            "markNo": np.tile(marks["markNo"].to_numpy(), n_wafers),
            "markXmm": np.tile(marks["markXmm"].round(3).to_numpy(), n_wafers),
            "markYmm": np.tile(marks["markYmm"].round(3).to_numpy(), n_wafers),
            "measX": values[:, :n_points].ravel().round(2),
            "measY": values[:, n_points:].ravel().round(2),
            "StsX": 0,
            "StsY": 0,
        }
    )
    labeled = np.zeros(n_wafers, dtype=int)
    labeled[[event["order"] - 1 for event in events if event["kind"] == "1 Wafer"]] = 1
    table[LABEL_COLUMN] = np.repeat(labeled, n_points)
    for axis in ("X", "Y"):
        missing = rng.random(len(table)) < STATUS_MISSING_RATE
        table.loc[missing, f"Sts{axis}"] = -1
        table.loc[missing, f"meas{axis}"] = 0.0  # 未測定の行に 0 が入っていても、アプリは使わない（ルールの確認用）
    duplicate = rng.random(len(table)) < DUPLICATE_RATE
    copies = table[duplicate].copy()
    for axis in ("X", "Y"):
        copies[f"meas{axis}"] = (copies[f"meas{axis}"] + rng.normal(0.0, DUPLICATE_NOISE_NM, len(copies))).round(2)
    table = pd.concat([table, copies]).sort_index(kind="stable").reset_index(drop=True)
    return table, pd.DataFrame(events)


def write_sample(folder: str | Path, kind: str = "csv", n_lots: int = DEFAULT_LOTS) -> list[Path]:
    """練習用データを保存する（CSV は UTF-8（BOM 付き）。Excel でそのまま開ける）。"""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    table, events = generate_sample_table(n_lots)
    stem = f"練習用_模擬データ_{n_lots * WAFERS_PER_LOT}枚"
    if kind == "csv":
        data_path = folder / f"{stem}.csv"
        table.to_csv(data_path, index=False, encoding="utf-8-sig", date_format="%Y/%m/%d %H:%M:%S")
    elif kind == "xlsx":
        data_path = folder / f"{stem}.xlsx"
        table.to_excel(data_path, index=False, sheet_name="計測データ")
    else:
        raise ValueError("kind は csv か xlsx")
    events_path = folder / f"{stem}_入れた異常.csv"
    events.rename(
        columns={"order": "何枚目", "kind": "種類", "pattern": "パターン", "amplitude_sigma": "大きさ（σ_dir）", "description": "内容"}
    ).to_csv(events_path, index=False, encoding="utf-8-sig")
    return [data_path, events_path]
