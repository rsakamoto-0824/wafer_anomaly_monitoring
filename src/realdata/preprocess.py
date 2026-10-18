"""計測テーブルの前処理（ユーザーの Overlay計測ルールに合わせる）。

- X の解析には StsX = 0 の measX、Y の解析には StsY = 0 の measY だけを使う。未測定（−1）などは欠測（NaN）にし、
  ゼロや有効な値として扱わない。Sts の列がなければ、数値が入っている計測値をすべて有効とみなす。
- 解析座標は x = Xmm + markXmm、y = Ymm + markYmm。有効な点は r < 有効半径（境界上の点は使わない）。
- Wafer・DateTime・Xmm・Ymm・markXmm・markYmm が同じ行は重複とみなし、計測値 X・Y をそれぞれ平均する。
  座標は丸め幅（既定 0.001 mm）で丸めてから比べる（ファイルによって小数の末尾が揺れることがあるため）。
- Radius の列があれば、Xmm・Ymm から計算した値と合っているかを確かめる（解析には計算値を使う）。
- 1回の計測（Wafer × DateTime）を1つの単位にする。時間の順番は DateTime、同じ日時（同じ Lot）の中では
  Wafer ID の自然な順（-2 が -10 より前）。DateTime がなければファイルの行の順番。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from .columns import duplicated_targets, missing_required
from .errors import UserFacingError
from .settings import DataOptions

UNIT_FACTORS = {"nm": 1.0, "um": 1000.0}
RADIUS_CHECK_TOLERANCE_MM = 0.01
DATETIME_DISPLAY_FORMAT = "%Y/%m/%d %H:%M:%S"
ABNORMAL_LABEL_WORDS = {"1", "true", "yes", "y", "ng", "異常", "abnormal", "bad", "anomaly", "fail", "x", "×"}
MAX_LISTED_VALUES = 500


@dataclass
class DataCheck:
    """前処理の記録（画面とファイルに出す）。"""

    n_rows_input: int = 0
    n_rows_filtered_out: int = 0
    n_rows_bad_wafer: int = 0
    n_rows_bad_coordinates: int = 0
    n_rows_bad_datetime: int = 0
    n_rows_outside_radius: int = 0
    n_rows_used: int = 0
    n_x_unmeasured: int = 0
    n_y_unmeasured: int = 0
    n_x_other_status: int = 0
    n_y_other_status: int = 0
    n_x_missing_value: int = 0
    n_y_missing_value: int = 0
    n_duplicate_groups: int = 0
    n_duplicate_extra_rows: int = 0
    n_radius_checked: int = 0
    n_radius_mismatch: int = 0
    max_radius_difference_mm: float = 0.0
    n_measurements: int = 0
    n_wafers: int = 0
    n_remeasured_wafers: int = 0
    n_dropped_remeasurements: int = 0
    n_points: int = 0
    n_shots: int = 0
    n_labeled: int = 0
    has_datetime: bool = False
    has_direction: bool = False
    has_status: bool = False
    has_label: bool = False
    datetime_first: str = ""
    datetime_last: str = ""
    valid_radius_mm: float = 150.0
    remeasure_policy: str = "all"
    warnings: list = field(default_factory=list)

    def summary_lines(self) -> list[str]:
        lines = [f"読み込んだ行：{self.n_rows_input:,} 行"]
        if self.n_rows_filtered_out:
            lines.append(f"絞り込みで除いた行：{self.n_rows_filtered_out:,} 行")
        bad = [
            (self.n_rows_bad_wafer, "Wafer が空欄"),
            (self.n_rows_bad_coordinates, "座標（Xmm・Ymm・markXmm・markYmm）が数値でない"),
            (self.n_rows_bad_datetime, "DateTime が日時として読めない"),
        ]
        for count, reason in bad:
            if count:
                lines.append(f"使えなかった行（{reason}）：{count:,} 行")
        lines.append(f"有効半径（r < {self.valid_radius_mm:g} mm）の外の行：{self.n_rows_outside_radius:,} 行（使わない）")
        lines.append(f"解析に使う行：{self.n_rows_used:,} 行")
        if self.has_status:
            lines.append(f"未測定（Sts = −1）：X {self.n_x_unmeasured:,} 個・Y {self.n_y_unmeasured:,} 個（欠測として扱う）")
            if self.n_x_other_status or self.n_y_other_status:
                lines.append(
                    f"状態コードが 0・−1 以外：X {self.n_x_other_status:,} 個・Y {self.n_y_other_status:,} 個（有効な値として使わない）"
                )
        if self.n_x_missing_value or self.n_y_missing_value:
            lines.append(f"計測値が空欄・数値でない：X {self.n_x_missing_value:,} 個・Y {self.n_y_missing_value:,} 個（欠測として扱う）")
        lines.append(
            f"重複行（同じ Wafer・日時・座標）：{self.n_duplicate_groups:,} 組（余分な行 {self.n_duplicate_extra_rows:,} 行）→ X・Y をそれぞれ平均"
        )
        if self.n_radius_checked:
            lines.append(
                f"Radius の確認：{self.n_radius_checked:,} 行のうち、Xmm・Ymm からの計算値と {RADIUS_CHECK_TOLERANCE_MM:g} mm 以上違う行 "
                f"{self.n_radius_mismatch:,} 行（最大の差 {self.max_radius_difference_mm:.4g} mm。解析には計算値を使う）"
            )
        policy = "すべて使う" if self.remeasure_policy == "all" else "最後の計測だけ使う"
        lines.append(
            f"計測（Wafer × 日時）：{self.n_measurements:,} 件、Wafer：{self.n_wafers:,} 枚、"
            f"2回以上計測された Wafer：{self.n_remeasured_wafers:,} 枚（{policy}）"
        )
        if self.n_dropped_remeasurements:
            lines.append(f"再計測とみなして除いた計測：{self.n_dropped_remeasurements:,} 件")
        lines.append(f"計測点：{self.n_points:,} 点（Shot {self.n_shots:,} 個）")
        if self.has_datetime:
            lines.append(f"計測日時：{self.datetime_first} 〜 {self.datetime_last}")
        if self.has_label:
            lines.append(f"ラベルで「異常」とされた計測：{self.n_labeled:,} 件")
        return lines


@dataclass
class PreparedData:
    measurements: pd.DataFrame  # 時間の順番に並んだ計測（order, Wafer, DateTime, label, n_rows）
    points: pd.DataFrame  # 計測点（Xmm, Ymm, markXmm, markYmm, x_mm, y_mm, r_mm, shot_id, shotNo, markNo, Direction）
    values: np.ndarray  # 計測 × 点 × 軸（X, Y）。欠測は NaN
    check: DataCheck
    options: DataOptions


# ---------------------------------------------------------------------- 値の変換
def normalize_value(value) -> str:
    """セルの値を比べるための文字列（Excel の 1.0 と CSV の 1 をそろえる）。"""
    if value is None or value is pd.NaT:
        return ""
    if isinstance(value, float):
        if np.isnan(value):
            return ""
        if value.is_integer():
            return str(int(value))
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.strftime(DATETIME_DISPLAY_FORMAT)
    if not isinstance(value, str) and pd.isna(value):
        return ""
    return str(value).strip()


def normalized_series(series: pd.Series) -> pd.Series:
    unique = pd.unique(series)
    lookup = {value: normalize_value(value) for value in unique}
    return series.map(lookup).fillna("")


def column_value_counts(table: pd.DataFrame, column: str) -> list[tuple[str, int]]:
    """列の値と件数（多い順、最大 MAX_LISTED_VALUES 個）。絞り込みとラベルの選択に使う。"""
    counts = normalized_series(table[column]).value_counts()
    return [(str(value), int(count)) for value, count in counts.head(MAX_LISTED_VALUES).items()]


def default_abnormal_values(values: list[str]) -> list[str]:
    """「異常」を表しそうな値（1、NG、異常 など。0 以外の数も含む）。"""
    chosen = []
    for value in values:
        lowered = value.strip().lower()
        if lowered in ABNORMAL_LABEL_WORDS:
            chosen.append(value)
            continue
        try:
            if float(lowered) != 0.0:
                chosen.append(value)
        except ValueError:
            pass
    return chosen


def natural_key(text: str) -> tuple:
    """数字の部分を数として比べる並べ方（W-2 が W-10 より前）。"""
    return tuple((0, int(part), "") if part.isdigit() else (1, 0, part.lower()) for part in re.split(r"(\d+)", text) if part)


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").astype(float)


def _datetime(series: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    unique = pd.unique(series)
    parsed = pd.to_datetime(pd.Series(unique, dtype=object), errors="coerce", format="mixed")
    lookup = dict(zip(unique, parsed))
    return series.map(lookup).astype("datetime64[ns]")


# ---------------------------------------------------------------------- 本体
def prepare(table: pd.DataFrame, options: DataOptions) -> PreparedData:
    mapping = options.mapping
    _check_mapping(table, options)
    check = DataCheck(
        n_rows_input=len(table),
        valid_radius_mm=float(options.valid_radius_mm),
        remeasure_policy=options.remeasure_policy,
        has_datetime=bool(mapping.get("DateTime")),
        has_direction=bool(mapping.get("Direction")),
        has_status=bool(mapping.get("StsX") or mapping.get("StsY")),
        has_label=bool(options.label_column),
    )

    if options.filter_column:
        wanted = {str(value) for value in options.filter_values}
        keep = normalized_series(table[options.filter_column]).isin(wanted)
        check.n_rows_filtered_out = int((~keep).sum())
        table = table[keep]

    work = pd.DataFrame(index=table.index)
    work["row"] = np.arange(len(table))
    work["Wafer"] = normalized_series(table[mapping["Wafer"]])
    for name in ("Xmm", "Ymm", "markXmm", "markYmm"):
        work[name] = _numeric(table[mapping[name]])
    factor = UNIT_FACTORS[options.measurement_unit]
    for axis, value_name, status_name in (("x", "measX", "StsX"), ("y", "measY", "StsY")):
        value = _numeric(table[mapping[value_name]]) * factor
        if mapping.get(status_name):
            status = _numeric(table[mapping[status_name]])
            valid = status == 0
            unmeasured = status == -1
            setattr(check, f"n_{axis}_unmeasured", int(unmeasured.sum()))
            setattr(check, f"n_{axis}_other_status", int((~valid & ~unmeasured).sum()))
        else:
            valid = pd.Series(True, index=table.index)
        setattr(check, f"n_{axis}_missing_value", int((value.isna() & valid).sum()))
        work[f"v{axis}"] = value.where(valid)
    work["DateTime"] = _datetime(table[mapping["DateTime"]]) if check.has_datetime else pd.NaT
    for name in ("shotNo", "markNo", "Direction"):
        work[name] = _numeric(table[mapping[name]]) if mapping.get(name) else np.nan
    if options.label_column:
        abnormal = {str(value) for value in options.label_abnormal_values}
        work["label"] = normalized_series(table[options.label_column]).isin(abnormal)
    else:
        work["label"] = False

    bad_wafer = work["Wafer"] == ""
    bad_coordinates = work[["Xmm", "Ymm", "markXmm", "markYmm"]].isna().any(axis=1) & ~bad_wafer
    bad_datetime = (work["DateTime"].isna() & check.has_datetime) & ~bad_wafer & ~bad_coordinates
    check.n_rows_bad_wafer = int(bad_wafer.sum())
    check.n_rows_bad_coordinates = int(bad_coordinates.sum())
    check.n_rows_bad_datetime = int(bad_datetime.sum())
    if mapping.get("Radius"):
        _check_radius(check, _numeric(table[mapping["Radius"]]), work, bad_wafer | bad_coordinates)
    work = work[~(bad_wafer | bad_coordinates | bad_datetime)].copy()

    work["x_mm"] = work["Xmm"] + work["markXmm"]
    work["y_mm"] = work["Ymm"] + work["markYmm"]
    outside = np.hypot(work["x_mm"], work["y_mm"]) >= options.valid_radius_mm
    check.n_rows_outside_radius = int(outside.sum())
    work = work[~outside].copy()
    check.n_rows_used = len(work)
    if work.empty:
        raise UserFacingError(
            "解析に使える行がありません。",
            "すべての行が、Wafer の空欄・座標の不足・日時の読み違い・有効半径の外のどれかで除かれました。",
            "列の対応づけ（特に座標の列）と有効半径の設定を確かめてください。",
        )

    _assign_point_keys(work, options.coordinate_tolerance_mm)
    measurements, work = _measurements(work, check, options)
    points = _points(work)
    values = np.full((len(measurements), len(points), 2), np.nan)
    grouped = work.groupby(["meas_index", "point_index"])[["vx", "vy"]]
    sizes = grouped.size()
    duplicated = sizes[sizes > 1]
    check.n_duplicate_groups = len(duplicated)
    check.n_duplicate_extra_rows = int((duplicated - 1).sum())
    means = grouped.mean()  # 欠測（NaN）は除いて平均する
    meas_index = means.index.get_level_values(0).to_numpy()
    point_index = means.index.get_level_values(1).to_numpy()
    values[meas_index, point_index, 0] = means["vx"].to_numpy()
    values[meas_index, point_index, 1] = means["vy"].to_numpy()

    check.n_points = len(points)
    check.n_shots = int(points["shot_id"].nunique())
    check.n_labeled = int(measurements["label"].sum())
    _add_warnings(check, options)
    return PreparedData(measurements, points, values, check, options)


def _check_mapping(table: pd.DataFrame, options: DataOptions) -> None:
    mapping = options.mapping
    missing = missing_required(mapping)
    if missing:
        raise UserFacingError(
            "必須の列が対応づけられていません：" + "、".join(missing),
            "これらの列がないと、計測点の位置や計測値が分かりません。",
            "「1. データ」の列の対応づけで、ファイルの列を選んでください。",
        )
    duplicated = duplicated_targets(mapping)
    if duplicated:
        raise UserFacingError(
            "同じ列が2つ以上の項目に割り当てられています：" + "、".join(duplicated),
            "1つの列は1つの項目にしか使えません。",
            "列の対応づけを見直してください。",
        )
    used = [column for column in mapping.values() if column]
    used += [column for column in (options.filter_column, options.label_column) if column]
    unknown = [column for column in used if column not in table.columns]
    if unknown:
        raise UserFacingError(
            "ファイルにない列が指定されています：" + "、".join(unknown),
            "別のファイルの設定を読み込んだか、ファイルの見出しが変わった可能性があります。",
            "列の対応づけ・絞り込み・ラベルの列を選び直してください。",
        )
    if options.filter_column and not options.filter_values:
        raise UserFacingError(
            "絞り込みの値が選ばれていません。",
            "絞り込みの列を選んだときは、残す値を1つ以上選ぶ必要があります。",
            "残す値を選ぶか、絞り込みの列を「（使わない）」にしてください。",
        )
    if options.label_column and not options.label_abnormal_values:
        raise UserFacingError(
            "ラベルの列で「異常」を表す値が選ばれていません。",
            "どの値が異常か分からないと、ラベルとの照合ができません。",
            "異常を表す値を選ぶか、ラベルの列を「（使わない）」にしてください。",
        )


def _check_radius(check: DataCheck, radius: pd.Series, work: pd.DataFrame, unusable: pd.Series) -> None:
    computed = np.hypot(work["Xmm"], work["Ymm"])
    target = radius.notna() & ~unusable
    difference = (radius - computed).abs()[target]
    check.n_radius_checked = int(target.sum())
    check.n_radius_mismatch = int((difference >= RADIUS_CHECK_TOLERANCE_MM).sum())
    check.max_radius_difference_mm = float(difference.max()) if len(difference) else 0.0


def _assign_point_keys(work: pd.DataFrame, tolerance_mm: float) -> None:
    for name, key in (("Xmm", "kx"), ("Ymm", "ky"), ("markXmm", "kmx"), ("markYmm", "kmy")):
        work[key] = np.round(work[name].to_numpy() / tolerance_mm).astype(np.int64)
    work["point_code"] = work.groupby(["kx", "ky", "kmx", "kmy"], sort=True).ngroup()
    work["shot_code"] = work.groupby(["kx", "ky"], sort=True).ngroup()


def _measurements(work: pd.DataFrame, check: DataCheck, options: DataOptions) -> tuple[pd.DataFrame, pd.DataFrame]:
    keys = ["Wafer", "DateTime"] if check.has_datetime else ["Wafer"]
    work["meas_code"] = work.groupby(keys, sort=False, dropna=False).ngroup()
    measurements = work.groupby("meas_code").agg(
        Wafer=("Wafer", "first"),
        DateTime=("DateTime", "first"),
        first_row=("row", "min"),
        n_rows=("row", "size"),
        label=("label", "max"),
    )
    counts = measurements.groupby("Wafer").size()
    check.n_remeasured_wafers = int((counts > 1).sum())
    if options.remeasure_policy == "last" and check.n_remeasured_wafers:
        latest = measurements.sort_values(["DateTime", "first_row"]).groupby("Wafer").tail(1).index
        check.n_dropped_remeasurements = len(measurements) - len(latest)
        measurements = measurements.loc[latest]
    if check.has_datetime:
        measurements["wafer_key"] = measurements["Wafer"].map(natural_key)
        measurements = measurements.sort_values(["DateTime", "wafer_key", "first_row"]).drop(columns="wafer_key")
    else:
        measurements = measurements.sort_values("first_row")
    measurements["meas_index"] = np.arange(len(measurements))
    work = work[work["meas_code"].isin(measurements.index)].copy()
    work["meas_index"] = work["meas_code"].map(measurements["meas_index"])
    measurements = measurements.reset_index(drop=True)
    measurements.insert(0, "order", np.arange(1, len(measurements) + 1))
    measurements["label"] = measurements["label"].astype(bool)
    check.n_measurements = len(measurements)
    check.n_wafers = int(measurements["Wafer"].nunique())
    if check.has_datetime:
        check.datetime_first = measurements["DateTime"].min().strftime(DATETIME_DISPLAY_FORMAT)
        check.datetime_last = measurements["DateTime"].max().strftime(DATETIME_DISPLAY_FORMAT)
    return measurements[["order", "Wafer", "DateTime", "label", "n_rows", "first_row", "meas_index"]], work


def _points(work: pd.DataFrame) -> pd.DataFrame:
    points = work.groupby("point_code").agg(
        Xmm=("Xmm", "median"),
        Ymm=("Ymm", "median"),
        markXmm=("markXmm", "median"),
        markYmm=("markYmm", "median"),
        shot_code=("shot_code", "first"),
        shotNo=("shotNo", "first"),
        markNo=("markNo", "first"),
        Direction=("Direction", "first"),
    )
    points["x_mm"] = points["Xmm"] + points["markXmm"]
    points["y_mm"] = points["Ymm"] + points["markYmm"]
    points["r_mm"] = np.hypot(points["x_mm"], points["y_mm"])
    # Shot の並び：shotNo があればその順、なければ上の行から左→右
    shot_order = points.groupby("shot_code").agg(shotNo=("shotNo", "first"), Ymm=("Ymm", "first"), Xmm=("Xmm", "first"))
    if shot_order["shotNo"].notna().all():
        shot_order = shot_order.sort_values(["shotNo", "Ymm", "Xmm"], ascending=[True, False, True])
    else:
        shot_order = shot_order.sort_values(["Ymm", "Xmm"], ascending=[False, True])
    shot_rank = pd.Series(np.arange(len(shot_order)), index=shot_order.index)
    points["shot_id"] = points["shot_code"].map(shot_rank)
    points = points.sort_values(["shot_id", "markNo", "markYmm", "markXmm"])
    points["point_index"] = np.arange(len(points))
    work["point_index"] = work["point_code"].map(points["point_index"])
    return points.reset_index(drop=True)[
        ["point_index", "Xmm", "Ymm", "markXmm", "markYmm", "x_mm", "y_mm", "r_mm", "shot_id", "shotNo", "markNo", "Direction"]
    ]


def _add_warnings(check: DataCheck, options: DataOptions) -> None:
    if not check.has_datetime:
        check.warnings.append("DateTime の列がないため、ファイルの行の順番を時間の順番として使います。")
    if not check.has_direction:
        check.warnings.append("Direction（Scan 方向）の列がないため、Scan 方向の異常（B8）の注入試験はできません。")
    if not check.has_status:
        check.warnings.append("StsX・StsY の列がないため、数値が入っている計測値をすべて有効とみなします。")
    if check.n_radius_mismatch:
        check.warnings.append(
            f"Radius が Xmm・Ymm からの計算値と合わない行が {check.n_radius_mismatch:,} 行あります。座標の列の対応づけを確かめてください。"
        )
    if check.n_remeasured_wafers and options.remeasure_policy == "all":
        check.warnings.append(
            f"2回以上計測された Wafer が {check.n_remeasured_wafers:,} 枚あります。それぞれ別の計測として時間の順番に並べます。"
            "再計測を除きたいときは「同じ Wafer の計測が複数あるとき」を「最後の計測だけ使う」にしてください。"
        )
