"""検証の設定（画面で入力する値）と、その既定値・保存・読み込み。

既定値は模擬データの検証（configs/default.yaml・技術レポート）に合わせる。
- 1 Wafer の手法：Phase 1 の系統別代表と、推奨の OR 統合（M3S・Mahalanobis 4次・PCA T²・SPE・GPR）に必要なもの
- 経時変化：Phase 2 の土台（M3S・係数SPC 4次・Mahalanobis 5次・PCA T²・SPE・GPR）。λ と k は Phase 2 の予備評価で選んだ値
  （results/metrics/phase2_pilot_selection.csv）を手法の系統ごとに使う
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .columns import COLUMN_NAMES

SETTINGS_VERSION = 1
ALPHA_CHOICES_PERCENT = (5.0, 1.0, 0.1)
POLYNOMIAL_ORDERS = (3, 4, 5)
PCA_SOURCES = ("raw", "coef")
PCA_RATIOS_PERCENT = (90, 95, 99)
PCA_COEF_ORDER = 5
GPR_VARIANTS = ("rbf_full", "rbf_residual", "matern52_full", "matern52_residual")
EWMA_LAMBDAS = (0.05, 0.1, 0.2, 0.4)
CUSUM_KS = (0.25, 0.5, 1.0)
SINGLE_PATTERNS = ("B1", "B2", "B3", "B4", "B5", "B7", "B8", "B9", "B10")
SINGLE_AMPLITUDES = (1.0, 2.0, 4.0, 8.0, 16.0)
TEMPORAL_COMPONENTS = ("low", "high", "radial", "tangential", "asymmetric", "local")
TEMPORAL_PROFILES = ("A1", "A2", "A3")
TEMPORAL_AMPLITUDES = (0.25, 0.5, 1.0, 2.0, 3.0)
TEMPORAL_PROFILE_PARAMS = {"ramp_length": 100, "drift_time_constant": 50, "period": 50}  # 検証と同じ

# 検証の Phase 2 予備評価で選んだ λ・k（系統ごと）。M1 は M3S のスカラーの EWMA・CUSUM
STUDY_TEMPORAL_PARAMETERS = {
    "M1": {"lambda": 0.1, "k": 0.25},
    "M2": {"lambda": 0.2, "k": 1.0},
    "M3": {"lambda": 0.05, "k": 1.0},
    "M4": {"lambda": 0.05, "k": 1.0},
    "M5": {"lambda": 0.05, "k": 1.0},
    "M6": {"lambda": 0.05, "k": 0.5},
}
STUDY_OR_MEMBERS = ["M3S_XY", "MD_d4", "T2_raw_q99", "SPE_raw_q99", "GPR_rbf_full"]
STUDY_TEMPORAL_BASES = ["M3S_XY", "SPC_d4", "MD_d5", "T2_raw_q99", "SPE_raw_q99", "GPR_rbf_full"]


@dataclass
class DataOptions:
    file_path: str = ""
    sheet: str | None = None
    mapping: dict = field(default_factory=lambda: {name: None for name in COLUMN_NAMES})
    measurement_unit: str = "nm"  # nm | um
    valid_radius_mm: float = 150.0  # この半径より内側（r < 値）の点だけ使う
    wafer_radius_mm: float = 150.0  # 正規化座標 x / R の R
    coordinate_tolerance_mm: float = 0.001  # 同じ計測点とみなす座標の丸め幅
    remeasure_policy: str = "all"  # all | last（同じ Wafer の計測が複数あるとき）
    filter_column: str | None = None
    filter_values: list = field(default_factory=list)
    label_column: str | None = None
    label_abnormal_values: list = field(default_factory=list)


@dataclass
class SplitOptions:
    normal_mode: str = "fraction"  # fraction | count | until
    normal_fraction_percent: float = 50.0
    normal_count: int = 200
    normal_until: str = ""  # 例 2026/09/30 23:59
    train_fraction_percent: float = 50.0
    min_point_rate_percent: float = 90.0
    max_missing_percent: float = 20.0


@dataclass
class MethodOptions:
    m3s: bool = True
    spc_orders: list = field(default_factory=lambda: [4])
    md_orders: list = field(default_factory=lambda: [4, 5])
    pca_sources: list = field(default_factory=lambda: ["raw"])
    pca_ratios: list = field(default_factory=lambda: [99])
    pca_t2: bool = True
    pca_spe: bool = True
    gpr_variants: list = field(default_factory=lambda: ["rbf_full"])
    alpha_percent: float = 1.0
    or_enabled: bool = True
    or_members: list = field(default_factory=lambda: list(STUDY_OR_MEMBERS))


@dataclass
class TemporalOptions:
    enabled: bool = True
    bases: list = field(default_factory=lambda: list(STUDY_TEMPORAL_BASES))
    parameter_mode: str = "study"  # study | custom
    lambdas: list = field(default_factory=lambda: [0.05, 0.2])
    ks: list = field(default_factory=lambda: [0.5, 1.0])
    include_shewhart: bool = True
    target_arl0: float = 370.0
    block_length: int = 25
    n_bootstrap_series: int = 200


@dataclass
class InjectionOptions:
    single_enabled: bool = True
    single_patterns: list = field(default_factory=lambda: list(SINGLE_PATTERNS))
    single_amplitudes: list = field(default_factory=lambda: [1.0, 2.0, 4.0, 8.0])
    single_replicates: int = 500
    temporal_enabled: bool = True
    temporal_components: list = field(default_factory=lambda: ["low", "high", "radial", "local"])
    temporal_profiles: list = field(default_factory=lambda: ["A1"])
    temporal_amplitudes: list = field(default_factory=lambda: [0.5, 1.0, 2.0])
    temporal_series: int = 100
    temporal_pre_length: int = 100
    temporal_window: int = 100


@dataclass
class AppSettings:
    data: DataOptions = field(default_factory=DataOptions)
    split: SplitOptions = field(default_factory=SplitOptions)
    methods: MethodOptions = field(default_factory=MethodOptions)
    temporal: TemporalOptions = field(default_factory=TemporalOptions)
    injection: InjectionOptions = field(default_factory=InjectionOptions)
    seed: int = 20261018

    def to_dict(self) -> dict:
        return {"version": SETTINGS_VERSION, **asdict(self)}

    @classmethod
    def from_dict(cls, values: dict) -> "AppSettings":
        """保存した設定から作る。知らない項目は無視し、ない項目は既定値にする（古い設定ファイルも読めるように）。"""
        sections = {"data": DataOptions, "split": SplitOptions, "methods": MethodOptions, "temporal": TemporalOptions, "injection": InjectionOptions}
        built = {}
        for key, section_cls in sections.items():
            source = values.get(key) or {}
            known = {f.name for f in fields(section_cls)}
            built[key] = section_cls(**{name: value for name, value in source.items() if name in known})
        settings = cls(**built, seed=int(values.get("seed", cls.seed)))
        mapping = {name: None for name in COLUMN_NAMES}
        mapping.update({name: column for name, column in (settings.data.mapping or {}).items() if name in mapping})
        settings.data.mapping = mapping
        return settings


def save_settings(settings: AppSettings, path: str | Path) -> None:
    Path(path).write_text(json.dumps(settings.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def load_settings(path: str | Path) -> AppSettings:
    return AppSettings.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


# ---------------------------------------------------------------------- 手法の名前
def pca_tag(source: str, ratio_percent: int) -> str:
    return f"{'raw' if source == 'raw' else f'coef{PCA_COEF_ORDER}'}_q{int(ratio_percent)}"


def selected_method_names(methods: MethodOptions) -> list[str]:
    """選んだ 1 Wafer の手法の名前（検証と同じ名前の付け方）。"""
    names = []
    if methods.m3s:
        names.append("M3S_XY")
    names += [f"SPC_d{order}" for order in sorted(methods.spc_orders)]
    names += [f"MD_d{order}" for order in sorted(methods.md_orders)]
    for source in [s for s in PCA_SOURCES if s in methods.pca_sources]:
        for ratio in sorted(methods.pca_ratios):
            if methods.pca_t2:
                names.append(f"T2_{pca_tag(source, ratio)}")
            if methods.pca_spe:
                names.append(f"SPE_{pca_tag(source, ratio)}")
    names += [f"GPR_{variant}" for variant in GPR_VARIANTS if variant in methods.gpr_variants]
    return names


def method_family(name: str) -> str:
    if name.startswith("OR["):
        return "OR"
    prefix = name.split("_")[0]
    return {"M3S": "M1", "SPC": "M2", "MD": "M3", "T2": "M4", "SPE": "M5", "GPR": "M6"}[prefix]


def method_label(name: str) -> str:
    """画面に出す手法の名前（日本語）。"""
    if name.startswith("OR["):
        return f"OR 統合（{len(or_members(name))} 手法）"
    parts = name.split("_")
    if name == "M3S_XY":
        return "M3S（XY）"
    if parts[0] == "SPC":
        return f"係数SPC（{parts[1][1:]}次）"
    if parts[0] == "MD":
        return f"Mahalanobis（{parts[1][1:]}次）"
    if parts[0] in ("T2", "SPE"):
        source = "計測値" if parts[1] == "raw" else f"{parts[1][4:]}次係数"
        head = "PCA T²" if parts[0] == "T2" else "PCA SPE"
        return f"{head}（{source}・{parts[2][1:]}%）"
    if parts[0] == "GPR":
        kernel = "RBF" if parts[1] == "rbf" else "Matérn"
        statistic = "全体" if parts[2] == "full" else "残差"
        return f"GPR（{kernel}・{statistic}）"
    return name


def or_name(members: list[str]) -> str:
    return "OR[" + "+".join(members) + "]"


def or_members(name: str) -> list[str]:
    return name[3:-1].split("+")


def or_members_label(name: str) -> str:
    return "・".join(method_label(member) for member in or_members(name))


def temporal_parameter_sets(temporal: TemporalOptions, base: str) -> tuple[list[float], list[float]]:
    """土台の手法ごとの λ と k の組。"""
    if temporal.parameter_mode == "study":
        chosen = STUDY_TEMPORAL_PARAMETERS[method_family(base)]
        return [chosen["lambda"]], [chosen["k"]]
    return sorted(temporal.lambdas), sorted(temporal.ks)


def validate_settings(settings: AppSettings) -> list[str]:
    """設定の誤り（日本語の文。空なら問題なし）。"""
    problems = []
    data, split, methods, temporal, injection = settings.data, settings.split, settings.methods, settings.temporal, settings.injection
    if data.measurement_unit not in ("nm", "um"):
        problems.append("計測値の単位は nm か µm を選んでください。")
    if not 0 < data.valid_radius_mm <= 1000 or not 0 < data.wafer_radius_mm <= 1000:
        problems.append("有効半径と Wafer の半径は 0 より大きい mm の値にしてください。")
    if not 0 < data.coordinate_tolerance_mm <= 1:
        problems.append("座標の丸め幅は 0 より大きく 1 mm 以下にしてください。")
    if split.normal_mode == "fraction" and not 10 <= split.normal_fraction_percent <= 100:
        problems.append("正常期間の割合は 10〜100% にしてください。")
    if split.normal_mode == "count" and split.normal_count < 40:
        problems.append("正常期間の枚数は 40 枚以上にしてください（学習と校正に 20 枚ずつ以上必要）。")
    if split.normal_mode == "until" and not split.normal_until.strip():
        problems.append("正常期間の終わりの日時を入力してください（例 2026/09/30 23:59）。")
    if not 20 <= split.train_fraction_percent <= 80:
        problems.append("学習に使う割合は 20〜80% にしてください（残りで管理限界を決めます）。")
    if not 50 <= split.min_point_rate_percent <= 100:
        problems.append("共通の計測点にする条件は 50〜100% にしてください。")
    if not 0 <= split.max_missing_percent <= 50:
        problems.append("Wafer を除く欠けの割合は 0〜50% にしてください。")
    names = selected_method_names(methods)
    if not names:
        problems.append("1 Wafer の監視手法を1つ以上選んでください。")
    if methods.alpha_percent not in ALPHA_CHOICES_PERCENT:
        problems.append("誤報率は 5%・1%・0.1% から選んでください。")
    if methods.or_enabled:
        missing = [member for member in methods.or_members if member not in names]
        if len(methods.or_members) < 2:
            problems.append("OR 統合には手法を2つ以上選んでください（使わない場合はチェックを外してください）。")
        elif missing:
            problems.append("OR 統合に、1 Wafer の手法で選んでいない手法が入っています：" + "、".join(method_label(m) for m in missing))
    if temporal.enabled:
        missing = [base for base in temporal.bases if base not in names]
        if not temporal.bases:
            problems.append("経時変化の監視に使う手法を1つ以上選んでください（使わない場合はチェックを外してください）。")
        elif missing:
            problems.append("経時変化の監視に、1 Wafer の手法で選んでいない手法が入っています：" + "、".join(method_label(m) for m in missing))
        if temporal.parameter_mode == "custom" and not (temporal.lambdas or temporal.ks or temporal.include_shewhart):
            problems.append("経時変化の監視で、λ（EWMA）か k（CUSUM）を1つ以上選んでください。")
        if not 50 <= temporal.target_arl0 <= 2000:
            problems.append("ARL₀ の目標は 50〜2000 枚にしてください。")
        if not 1 <= temporal.block_length <= 200:
            problems.append("ブロックの長さは 1〜200 枚にしてください。")
        if not 50 <= temporal.n_bootstrap_series <= 2000:
            problems.append("再標本化の系列数は 50〜2000 にしてください。")
    if injection.single_enabled:
        if not injection.single_patterns:
            problems.append("1 Wafer の注入試験の異常パターンを1つ以上選んでください。")
        if not injection.single_amplitudes:
            problems.append("1 Wafer の注入試験の大きさを1つ以上選んでください。")
        if not 50 <= injection.single_replicates <= 5000:
            problems.append("1 Wafer の注入試験の回数は 50〜5000 にしてください。")
    if injection.temporal_enabled:
        if not temporal.enabled:
            problems.append("経時変化の注入試験には、経時変化の監視（EWMA・CUSUM）を有効にしてください。")
        if not (injection.temporal_components and injection.temporal_profiles and injection.temporal_amplitudes):
            problems.append("経時変化の注入試験の成分・変化の形・大きさを1つ以上ずつ選んでください。")
        if not 20 <= injection.temporal_series <= 2000:
            problems.append("経時変化の注入試験の系列数は 20〜2000 にしてください。")
        if not 10 <= injection.temporal_pre_length <= 1000 or not 10 <= injection.temporal_window <= 1000:
            problems.append("変化前の枚数と観測する枚数は 10〜1000 枚にしてください。")
    return problems
