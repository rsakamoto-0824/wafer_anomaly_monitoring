"""共通の計測点、欠けた点の補完、学習・校正・評価への分割。

検証の手法（PCA・GPR など）は「どの Wafer も同じ点を計測している」ことを前提にする（固定グリッド）。
実データでは点が欠けることがあるので、次のように扱う。
1. 正常期間の計測で、計測できた割合が条件（既定 90%）以上の点を「共通の計測点」にする。
2. 共通の計測点のうち欠けが多い計測（既定 20% 超）は解析から除く（理由を記録する）。
3. 残った欠けは、正常の学習データから作るモデル（PPCA）で「同じ Wafer のほかの点から見た期待値」で補う。
   補った値は M3S には使わない（M3S は計測できた値だけで計算する）。

分割は時間の順番で、正常期間の前半を学習（正常のモデル）、後半を校正（管理限界）、正常期間より後を評価にする
（検証の「学習・閾値校正・評価を別々のデータで行う」に合わせる）。ラベルで異常とされた計測は学習・校正に使わない。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..wafer_geometry import PointSet
from .errors import UserFacingError
from .preprocess import PreparedData
from .settings import SplitOptions

SEGMENT_TRAIN = "学習"
SEGMENT_CALIBRATION = "校正"
SEGMENT_EVALUATION = "評価"
SEGMENT_LABEL_EXCLUDED = "正常期間（ラベルで除外）"
SEGMENT_EXCLUDED = "除外"
SEGMENT_ORDER = (SEGMENT_TRAIN, SEGMENT_CALIBRATION, SEGMENT_LABEL_EXCLUDED, SEGMENT_EVALUATION, SEGMENT_EXCLUDED)
MIN_TRAIN = 20
MIN_CALIBRATION = 20
MIN_MAP_POINTS = 10
MIN_TRAIN_PRESENCE = 0.5  # 学習期間で半分以上計測できていない点は、補完のモデルが作れないので使わない
IMPUTE_VARIANCE_RATIO = 0.95
IMPUTE_MAX_COMPONENTS = 30
IMPUTE_ITERATIONS = 10
IMPUTE_TOLERANCE = 1e-4


class PPCAImputer:
    """確率的主成分分析（PPCA）で欠けた値を補う。

    正常の学習データに z = μ + W t + ε（t ~ N(0, I)、ε ~ N(0, σ² I)）を当てはめ、欠けた値を
    同じ Wafer の計測できた点から見た条件付き期待値 μ_M + W_M (W_Oᵀ W_O + σ² I)⁻¹ W_Oᵀ (z_O − μ_O) で補う。
    学習データ自身の欠けは、補完と当てはめを交互に繰り返して決める（EM 法を簡略にしたもの）。
    補った値は正常のモデルに引き寄せられるので、欠けた点にある異常は見えない（補った数を結果に出す）。
    """

    def __init__(self, variance_ratio: float = IMPUTE_VARIANCE_RATIO, max_components: int = IMPUTE_MAX_COMPONENTS):
        self.variance_ratio = variance_ratio
        self.max_components = max_components

    def fit(self, observed: np.ndarray) -> "PPCAImputer":
        mask = np.isnan(observed)
        mean = np.nanmean(observed, axis=0)
        filled = np.where(mask, mean, observed)
        rows = np.flatnonzero(mask.any(axis=1))
        scale = float(np.nanstd(observed)) or 1.0
        self.iterations_ = 0
        for _ in range(IMPUTE_ITERATIONS):
            self._fit_model(filled)
            self.iterations_ += 1
            if len(rows) == 0:
                break
            updated = self._conditional(observed[rows], mask[rows])
            change = float(np.max(np.abs(updated - filled[rows]))) / scale
            filled[rows] = updated
            if change < IMPUTE_TOLERANCE:
                break
        self._fit_model(filled)
        return self

    def _fit_model(self, filled: np.ndarray) -> None:
        self.mean_ = filled.mean(axis=0)
        centered = filled - self.mean_
        _, singular, vt = np.linalg.svd(centered, full_matrices=False)
        eigenvalues = singular**2 / max(len(filled) - 1, 1)
        total = float(eigenvalues.sum())
        if total <= 0 or len(eigenvalues) < 2:
            self.components_ = np.zeros((filled.shape[1], 0))
            self.noise_variance_ = max(total, 1e-12)
            return
        cumulative = np.cumsum(eigenvalues) / total
        k = int(np.searchsorted(cumulative, self.variance_ratio) + 1)
        k = max(1, min(k, self.max_components, len(eigenvalues) - 1))
        rest = eigenvalues[k:]
        self.noise_variance_ = max(float(rest.mean()), 1e-12 * total / len(eigenvalues))
        self.components_ = vt[:k].T * np.sqrt(np.maximum(eigenvalues[:k] - self.noise_variance_, 0.0))

    def _conditional(self, values: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """欠けのある行を補う（欠け方が同じ行はまとめて計算する）。"""
        output = np.where(mask, 0.0, values)
        groups: dict[bytes, list[int]] = {}
        for index, row_mask in enumerate(mask):
            if row_mask.any():
                groups.setdefault(row_mask.tobytes(), []).append(index)
        w = self.components_
        for members in groups.values():
            missing = mask[members[0]]
            observed = ~missing
            w_obs = w[observed]
            precision = w_obs.T @ w_obs + self.noise_variance_ * np.eye(w.shape[1])
            centered = values[np.ix_(members, observed)] - self.mean_[observed]
            latent = np.linalg.solve(precision, w_obs.T @ centered.T) if w.shape[1] else np.zeros((0, len(members)))
            output[np.ix_(members, missing)] = self.mean_[missing] + (w[missing] @ latent).T
        return output

    def transform(self, observed: np.ndarray) -> np.ndarray:
        mask = np.isnan(observed)
        if not mask.any():
            return observed.copy()
        return self._conditional(observed, mask)


@dataclass
class AnalysisDataset:
    prepared: PreparedData
    measurements: pd.DataFrame  # 全計測（order, Wafer, DateTime, label, segment, used, row, missing_percent, n_imputed, reason）
    map_points: pd.DataFrame  # 共通の計測点（presence_percent など）
    points: PointSet
    observed: np.ndarray  # 使う計測 × 2N（前半 X、後半 Y。欠測は NaN）
    filled: np.ndarray  # 欠けを補ったもの
    imputer: PPCAImputer
    n_normal: int
    notes: list

    @property
    def n_points(self) -> int:
        return len(self.points)

    def rows(self, *segments: str) -> np.ndarray:
        """指定した区分の計測の行番号（observed・filled の行。時間の順番）。"""
        table = self.measurements[self.measurements["used"]]
        return table.loc[table["segment"].isin(segments), "row"].to_numpy(dtype=int)

    @property
    def used(self) -> pd.DataFrame:
        return self.measurements[self.measurements["used"]].sort_values("row")


def normal_period_mask(measurements: pd.DataFrame, split: SplitOptions, has_datetime: bool) -> np.ndarray:
    count = len(measurements)
    if split.normal_mode == "fraction":
        n_normal = int(np.ceil(split.normal_fraction_percent / 100.0 * count))
        return measurements["order"].to_numpy() <= n_normal
    if split.normal_mode == "count":
        return measurements["order"].to_numpy() <= min(int(split.normal_count), count)
    if split.normal_mode == "until":
        if not has_datetime:
            raise UserFacingError(
                "日時で正常期間を決められません。",
                "DateTime の列が対応づけられていないため、計測の日時が分かりません。",
                "正常期間を「先頭からの割合」か「先頭からの枚数」で指定するか、DateTime の列を対応づけてください。",
            )
        until = pd.to_datetime(split.normal_until.strip(), errors="coerce", format="mixed")
        if pd.isna(until):
            raise UserFacingError(
                f"正常期間の終わりの日時「{split.normal_until}」を読み取れません。",
                "日時の書き方が想定と違います。",
                "2026/09/30 23:59 のように「年/月/日 時:分」で入力してください。",
            )
        return (measurements["DateTime"] <= until).to_numpy()
    raise ValueError(f"未知の正常期間の指定: {split.normal_mode}")


def build_dataset(prepared: PreparedData, split: SplitOptions, wafer_radius_mm: float) -> AnalysisDataset:
    measurements = prepared.measurements.copy()
    values = prepared.values
    notes = []
    normal = normal_period_mask(measurements, split, prepared.check.has_datetime)
    labeled = measurements["label"].to_numpy(dtype=bool)
    candidates = normal & ~labeled
    if candidates.sum() < MIN_TRAIN + MIN_CALIBRATION:
        raise _too_few_error(int(candidates.sum()), "正常期間")

    both_valid = ~np.isnan(values).any(axis=2)  # 計測 × 点（X・Y の両方が計測できた）
    presence = both_valid[candidates].mean(axis=0)
    in_map = presence >= split.min_point_rate_percent / 100.0
    if in_map.sum() < MIN_MAP_POINTS:
        raise UserFacingError(
            f"共通の計測点が {int(in_map.sum())} 点しかありません。",
            f"正常期間の {split.min_point_rate_percent:g}% 以上で計測できた点が少なすぎます（計測点の配置が Wafer ごとに違う可能性があります）。",
            "「共通の計測点にする条件」の割合を下げるか、絞り込みで同じ計測レシピのデータだけにしてください。",
        )

    map_index = np.flatnonzero(in_map)
    segment, missing_percent = _assign_segments(values, map_index, normal, labeled, split)
    train_rows_mask = segment == SEGMENT_TRAIN
    train_presence = both_valid[np.ix_(train_rows_mask, map_index)].mean(axis=0)
    weak = train_presence < MIN_TRAIN_PRESENCE
    if weak.any():
        notes.append(f"学習期間で半分以上計測できていない {int(weak.sum())} 点を共通の計測点から除きました。")
        map_index = map_index[~weak]
        segment, missing_percent = _assign_segments(values, map_index, normal, labeled, split)

    n_train = int((segment == SEGMENT_TRAIN).sum())
    n_calibration = int((segment == SEGMENT_CALIBRATION).sum())
    if n_train < MIN_TRAIN or n_calibration < MIN_CALIBRATION:
        raise _too_few_error(n_train + n_calibration, "欠けの多い計測を除いたあとの正常期間")

    used = segment != SEGMENT_EXCLUDED
    measurements["segment"] = segment
    measurements["used"] = used
    measurements["missing_percent"] = missing_percent
    measurements["reason"] = np.where(
        used, "", [f"共通の計測点の {p:.1f}% が欠けている（上限 {split.max_missing_percent:g}%）" for p in missing_percent]
    )
    measurements["row"] = -1
    measurements.loc[used, "row"] = np.arange(int(used.sum()))

    selected = values[np.ix_(used, map_index)]  # 使う計測 × 点 × 軸
    observed = np.concatenate([selected[..., 0], selected[..., 1]], axis=1)
    imputer = PPCAImputer().fit(observed[measurements.loc[used, "segment"].to_numpy() == SEGMENT_TRAIN])
    filled = imputer.transform(observed)
    measurements["n_imputed"] = 0
    measurements.loc[used, "n_imputed"] = np.isnan(observed).sum(axis=1)

    map_points = prepared.points.iloc[map_index].copy()
    map_points["presence_percent"] = 100.0 * presence[map_index]
    map_points = map_points.reset_index(drop=True)
    points = _point_set(map_points, wafer_radius_mm)
    excluded_points = len(prepared.points) - len(map_points)
    if excluded_points:
        notes.append(f"計測できた割合が少ない {excluded_points} 点は、共通の計測点に入れませんでした（どの手法にも使わない）。")
    return AnalysisDataset(prepared, measurements, map_points, points, observed, filled, imputer, int(normal.sum()), notes)


def _assign_segments(values, map_index, normal, labeled, split: SplitOptions) -> tuple[np.ndarray, np.ndarray]:
    on_map = values[:, map_index, :]
    missing_percent = 100.0 * np.isnan(on_map).mean(axis=(1, 2))
    excluded = missing_percent > split.max_missing_percent
    segment = np.where(normal, SEGMENT_LABEL_EXCLUDED, SEGMENT_EVALUATION).astype(object)
    normal_usable = np.flatnonzero(normal & ~labeled & ~excluded)  # 時間の順番（measurements は order 順）
    n_train = int(round(split.train_fraction_percent / 100.0 * len(normal_usable)))
    segment[normal_usable[:n_train]] = SEGMENT_TRAIN
    segment[normal_usable[n_train:]] = SEGMENT_CALIBRATION
    segment[excluded] = SEGMENT_EXCLUDED
    return segment, missing_percent


def _point_set(map_points: pd.DataFrame, wafer_radius_mm: float) -> PointSet:
    shot_index = pd.factorize(map_points["shot_id"], sort=True)[0]
    if map_points["markNo"].notna().all():
        mark_no = map_points["markNo"].to_numpy(dtype=int)
    else:
        mark_no = map_points.groupby("shot_id").cumcount().to_numpy() + 1
    direction = map_points["Direction"].fillna(0).to_numpy(dtype=int)
    return PointSet(
        map_points["x_mm"].to_numpy(dtype=float),
        map_points["y_mm"].to_numpy(dtype=float),
        shot_index,
        mark_no,
        direction,
        float(wafer_radius_mm),
    )


def _too_few_error(count: int, where: str) -> UserFacingError:
    return UserFacingError(
        f"{where}の計測が {count} 件しかありません。",
        f"正常のモデルの学習と管理限界の決定に、それぞれ {MIN_TRAIN} 件以上（合計 {MIN_TRAIN + MIN_CALIBRATION} 件以上）必要です。",
        "正常期間を長くする（割合・枚数を増やす）か、欠けの条件をゆるめてください。",
    )
