"""「2. 設定」の画面：正常期間と分割、欠けの扱い、監視手法、経時変化の監視、異常の注入試験。"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import numpy as np

from ..analysis import run_analysis
from ..dataset import normal_period_mask
from ..errors import UserFacingError
from ..injection import COMPONENT_LABELS, PATTERN_DESCRIPTIONS, PATTERN_LABELS, PROFILE_LABELS
from ..settings import (
    ALPHA_CHOICES_PERCENT,
    CUSUM_KS,
    EWMA_LAMBDAS,
    GPR_VARIANTS,
    PCA_RATIOS_PERCENT,
    POLYNOMIAL_ORDERS,
    SINGLE_AMPLITUDES,
    SINGLE_PATTERNS,
    STUDY_OR_MEMBERS,
    TEMPORAL_AMPLITUDES,
    TEMPORAL_COMPONENTS,
    TEMPORAL_PROFILES,
    AppSettings,
    InjectionOptions,
    MethodOptions,
    SplitOptions,
    TemporalOptions,
    method_label,
    selected_method_names,
    validate_settings,
)
from .widgets import PAD, SMALL_PAD, CheckGroup, ScrollableFrame, ToolTip, labeled_row, read_float, read_int, show_error

GPR_LABELS = {"rbf_full": "RBF・全体", "rbf_residual": "RBF・残差", "matern52_full": "Matérn・全体", "matern52_residual": "Matérn・残差"}
GPR_TIPS = {
    "rbf_full": "滑らかな個体差も含めた、GP の下での Mahalanobis 距離（検証の系統別代表）",
    "rbf_residual": "滑らかな個体差を除いた残差（Shot・Mark 単位の急なずれに反応）",
    "matern52_full": "Matérn 5/2 カーネル。RBF より少し粗い変動を許す",
    "matern52_residual": "Matérn 5/2 カーネルの残差",
}
NOT_READY_TEXT = "「1. データ」で「データを確認する」を押すと実行できます。"
PATTERN_TIPS = {pattern: PATTERN_DESCRIPTIONS.get(pattern, "") for pattern in SINGLE_PATTERNS}


class SettingsTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        scroll = ScrollableFrame(self)
        scroll.pack(fill="both", expand=True)
        body = scroll.inner
        body.columnconfigure(0, weight=1)
        ttk.Label(body, text="2. 検証の設定", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            body,
            text="既定の値は、模擬データの検証（技術レポート）と同じです。分からない項目はそのままで構いません。",
            style="Note.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(0, PAD))
        self._split_section(body, 2)
        self._missing_section(body, 3)
        self._method_section(body, 4)
        self._temporal_section(body, 5)
        self._injection_section(body, 6)
        other = ttk.LabelFrame(body, text="その他", padding=PAD)
        other.grid(row=7, column=0, sticky="ew", pady=SMALL_PAD)
        self.seed_var = tk.StringVar()
        labeled_row(other, 0, "乱数の種", ttk.Entry(other, textvariable=self.seed_var, width=12),
                    "注入試験と管理限界の再標本化に使う乱数。同じ値なら同じ結果になります。")

        bar = ttk.Frame(self, padding=(PAD, SMALL_PAD))
        bar.pack(side="bottom", fill="x")
        ttk.Separator(self, orient="horizontal").pack(side="bottom", fill="x")
        self.defaults_button = ttk.Button(bar, text="既定の値に戻す", command=self.reset_defaults)
        self.defaults_button.pack(side="left")
        self.status = ttk.Label(bar, text="", style="Note.TLabel")
        self.status.pack(side="left", padx=PAD)
        self.run_button = ttk.Button(bar, text="検証を実行", style="Primary.TButton", command=self.run)
        self.run_button.pack(side="right")
        self.apply_settings(AppSettings())

    # ------------------------------------------------------------------ 画面の組み立て
    def _split_section(self, body, row):
        box = ttk.LabelFrame(body, text="正常期間と分割（時間の順番で分けます）", padding=PAD)
        box.grid(row=row, column=0, sticky="ew", pady=SMALL_PAD)
        self.normal_mode_var = tk.StringVar(value="fraction")
        self.normal_fraction_var = tk.StringVar()
        self.normal_count_var = tk.StringVar()
        self.normal_until_var = tk.StringVar()
        modes = ttk.Frame(box)
        modes.grid(row=0, column=0, columnspan=3, sticky="w")
        for column, (value, text, variable, width, unit) in enumerate(
            (
                ("fraction", "先頭からの割合", self.normal_fraction_var, 6, "%"),
                ("count", "先頭からの件数", self.normal_count_var, 8, "件"),
                ("until", "この日時まで", self.normal_until_var, 20, "（例 2026/09/30 23:59）"),
            )
        ):
            frame = ttk.Frame(modes)
            frame.grid(row=0, column=column, sticky="w", padx=(0, 3 * PAD))
            ttk.Radiobutton(frame, text=text, value=value, variable=self.normal_mode_var, command=self.update_preview).pack(side="left")
            entry = ttk.Entry(frame, textvariable=variable, width=width)
            entry.pack(side="left", padx=SMALL_PAD)
            entry.bind("<FocusOut>", lambda _e: self.update_preview())
            entry.bind("<Return>", lambda _e: self.update_preview())
            ttk.Label(frame, text=unit).pack(side="left")
        ttk.Label(box, text="正常期間：異常がないと考えられる期間。この期間で正常のモデルを学習し、管理限界を決めます。それより後が評価期間です。",
                  style="Note.TLabel", wraplength=900, justify="left").grid(row=1, column=0, columnspan=3, sticky="w", pady=SMALL_PAD)
        self.train_fraction_var = tk.StringVar()
        entry = ttk.Entry(box, textvariable=self.train_fraction_var, width=6)
        entry.bind("<FocusOut>", lambda _e: self.update_preview())
        labeled_row(box, 1, "正常期間のうち学習に使う割合（%）", entry, "前半を学習（正常のモデル）、後半を校正（管理限界）に使います。")
        self.preview_label = ttk.Label(box, text="", style="Section.TLabel")
        self.preview_label.grid(row=4, column=0, columnspan=3, sticky="w", pady=(SMALL_PAD, 0))

    def _missing_section(self, body, row):
        box = ttk.LabelFrame(body, text="計測点の欠け", padding=PAD)
        box.grid(row=row, column=0, sticky="ew", pady=SMALL_PAD)
        self.min_point_rate_var = tk.StringVar()
        self.max_missing_var = tk.StringVar()
        labeled_row(box, 0, "共通の計測点にする条件（%）", ttk.Entry(box, textvariable=self.min_point_rate_var, width=6),
                    "正常期間の計測のうち、この割合以上で計測できた点を、すべての手法で使う「共通の計測点」にします。")
        labeled_row(box, 1, "計測を除く欠けの割合（%）", ttk.Entry(box, textvariable=self.max_missing_var, width=6),
                    "共通の計測点のうち、この割合より多く欠けている計測は解析から除きます。残りの欠けは正常のモデルで補います（M3S には使いません）。")

    def _method_section(self, body, row):
        box = ttk.LabelFrame(body, text="1 Wafer の監視手法（同じ誤報率にそろえて比べます）", padding=PAD)
        box.grid(row=row, column=0, sticky="ew", pady=SMALL_PAD)
        self.alpha_var = tk.StringVar()
        alpha = ttk.Frame(box)
        for value in ALPHA_CHOICES_PERCENT:
            ttk.Radiobutton(alpha, text=f"{value:g}%", value=f"{value:g}", variable=self.alpha_var, command=self.update_preview).pack(side="left", padx=(0, PAD))
        labeled_row(box, 0, "誤報率（正常の Wafer で警報が出る割合）", alpha, "校正の件数 × 誤報率が 5 件以上あると管理限界が安定します（1% なら 500 件）。")
        self.m3s_var = tk.BooleanVar()
        ttk.Checkbutton(box, text="M1 M3S（|平均| + 3σ、X・Y の大きいほう）", variable=self.m3s_var, command=self.methods_changed).grid(row=2, column=0, columnspan=3, sticky="w", pady=2)
        self.spc_group = CheckGroup(box, [(o, f"{o}次") for o in POLYNOMIAL_ORDERS], command=self.methods_changed)
        labeled_row(box, 2, "M2 多項式係数の SPC", self.spc_group, "係数ごとの管理図（どれか1つでも外れたら警報）")
        self.md_group = CheckGroup(box, [(o, f"{o}次") for o in POLYNOMIAL_ORDERS], command=self.methods_changed)
        labeled_row(box, 3, "M3 係数の Mahalanobis 距離", self.md_group, "係数の組み合わせのずれ（縮小推定 Ledoit–Wolf）")
        pca = ttk.Frame(box)
        self.pca_source_group = CheckGroup(pca, [("raw", "計測値"), ("coef", "5次係数")], command=self.methods_changed)
        self.pca_source_group.pack(side="left")
        ttk.Label(pca, text="寄与率").pack(side="left", padx=(PAD, SMALL_PAD))
        self.pca_ratio_group = CheckGroup(pca, [(r, f"{r}%") for r in PCA_RATIOS_PERCENT], command=self.methods_changed)
        self.pca_ratio_group.pack(side="left")
        ttk.Label(pca, text="統計量").pack(side="left", padx=(PAD, SMALL_PAD))
        self.pca_stat_group = CheckGroup(pca, [("t2", "T²"), ("spe", "SPE")], command=self.methods_changed)
        self.pca_stat_group.pack(side="left")
        labeled_row(box, 4, "M4・M5 PCA", pca, "T²＝主成分の中のずれ、SPE＝主成分で表せないずれ")
        self.gpr_group = CheckGroup(box, [(v, GPR_LABELS[v]) for v in GPR_VARIANTS], command=self.methods_changed, tooltips=GPR_TIPS)
        labeled_row(box, 5, "M6 GPR", self.gpr_group, "点が多いと計算に時間がかかります（1500 点まで）")
        self.or_var = tk.BooleanVar()
        or_frame = ttk.Frame(box)
        ttk.Checkbutton(or_frame, text="使う", variable=self.or_var, command=self.methods_changed).pack(side="left")
        ttk.Button(or_frame, text="検証の推奨（5手法）に戻す", command=self.reset_or_members).pack(side="left", padx=PAD)
        labeled_row(box, 6, "OR 統合（どれか1つでも警報）", or_frame, "統合したあとの誤報率が上の値になるように、各手法の限界をそろえます。")
        self.or_group = CheckGroup(box, [], columns=3)
        self.or_group.grid(row=14, column=1, columnspan=2, sticky="w")

    def _temporal_section(self, body, row):
        box = ttk.LabelFrame(body, text="経時変化の監視（EWMA・CUSUM。正常時の平均連長 ARL₀ にそろえて比べます）", padding=PAD)
        box.grid(row=row, column=0, sticky="ew", pady=SMALL_PAD)
        self.temporal_var = tk.BooleanVar()
        ttk.Checkbutton(box, text="経時変化の監視を行う", variable=self.temporal_var, command=self.methods_changed).grid(row=0, column=0, columnspan=3, sticky="w")
        self.temporal_bases = CheckGroup(box, [], columns=3)
        labeled_row(box, 1, "土台にする手法", self.temporal_bases)
        self.parameter_mode_var = tk.StringVar()
        mode = ttk.Frame(box)
        ttk.Radiobutton(mode, text="検証で選ばれた値（手法ごと）", value="study", variable=self.parameter_mode_var, command=self._mode_changed).pack(side="left")
        ttk.Radiobutton(mode, text="自分で選ぶ", value="custom", variable=self.parameter_mode_var, command=self._mode_changed).pack(side="left", padx=PAD)
        labeled_row(box, 2, "λ（EWMA）と k（CUSUM）", mode,
                    "検証の値：M3S λ=0.1・k=0.25、係数SPC λ=0.2・k=1、Mahalanobis・PCA λ=0.05・k=1、GPR λ=0.05・k=0.5")
        self.lambda_group = CheckGroup(box, [(v, f"λ={v:g}") for v in EWMA_LAMBDAS])
        labeled_row(box, 3, "　λ（小さいほど長く平均する）", self.lambda_group)
        self.k_group = CheckGroup(box, [(v, f"k={v:g}") for v in CUSUM_KS])
        labeled_row(box, 4, "　k（小さいほど小さな変化に敏感）", self.k_group)
        self.shewhart_var = tk.BooleanVar()
        ttk.Checkbutton(box, text="Shewhart（1枚ごとの判定）も同じ ARL₀ で比べる", variable=self.shewhart_var).grid(row=10, column=0, columnspan=3, sticky="w")
        self.arl_var, self.block_var, self.bootstrap_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        labeled_row(box, 6, "ARL₀ の目標（枚）", ttk.Entry(box, textvariable=self.arl_var, width=8),
                    "正常時に、最初の誤報が出るまでの平均の枚数。370 は 3σ の管理図と同じ。校正の件数が目標の 2 倍以上あると確かです。")
        labeled_row(box, 7, "ブロックの長さ（枚）", ttk.Entry(box, textvariable=self.block_var, width=8),
                    "校正期間の Wafer をこの枚数ずつつないで長い正常系列を作り、管理限界を決めます（25 枚＝1 Lot）。")
        labeled_row(box, 8, "再標本化の系列数", ttk.Entry(box, textvariable=self.bootstrap_var, width=8), "多いほど管理限界が安定しますが、時間がかかります。")

    def _injection_section(self, body, row):
        box = ttk.LabelFrame(body, text="異常の注入試験（実データの正常 Wafer に、検証と同じ形の異常を足して検出率を比べます）", padding=PAD)
        box.grid(row=row, column=0, sticky="ew", pady=SMALL_PAD)
        self.single_var = tk.BooleanVar()
        ttk.Checkbutton(box, text="1 Wafer の注入試験を行う（検証の Phase 1）", variable=self.single_var).grid(row=0, column=0, columnspan=3, sticky="w")
        self.pattern_group = CheckGroup(box, [(p, f"{p} {PATTERN_LABELS[p]}") for p in SINGLE_PATTERNS], columns=3, tooltips=PATTERN_TIPS)
        labeled_row(box, 1, "異常の形", self.pattern_group)
        self.single_amp_group = CheckGroup(box, [(a, f"{a:g}σ") for a in SINGLE_AMPLITUDES], columns=5)
        labeled_row(box, 2, "大きさ（σ_dir の倍数）", self.single_amp_group, "σ_dir：異常の形の向きでの、正常 Wafer のばらつき（標準偏差）。")
        self.replicate_var = tk.StringVar()
        labeled_row(box, 3, "条件ごとの回数", ttk.Entry(box, textvariable=self.replicate_var, width=8))
        ttk.Separator(box, orient="horizontal").grid(row=8, column=0, columnspan=3, sticky="ew", pady=PAD)
        self.temporal_injection_var = tk.BooleanVar()
        ttk.Checkbutton(box, text="経時変化の注入試験を行う（検証の Phase 2。経時変化の監視が必要）", variable=self.temporal_injection_var).grid(row=10, column=0, columnspan=3, sticky="w")
        self.component_group = CheckGroup(box, [(c, COMPONENT_LABELS[c]) for c in TEMPORAL_COMPONENTS], columns=2)
        labeled_row(box, 6, "変化する成分", self.component_group)
        self.profile_group = CheckGroup(box, [(p, f"{p} {PROFILE_LABELS[p]}") for p in TEMPORAL_PROFILES], columns=3)
        labeled_row(box, 7, "変化の形", self.profile_group, "Ramp は 100 枚で指定の大きさに達し、その後も増え続けます。")
        self.temporal_amp_group = CheckGroup(box, [(a, f"{a:g}σ") for a in TEMPORAL_AMPLITUDES], columns=5)
        labeled_row(box, 8, "大きさ（σ_dir の倍数）", self.temporal_amp_group)
        self.series_var, self.pre_var, self.window_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        labeled_row(box, 9, "系列数", ttk.Entry(box, textvariable=self.series_var, width=8))
        labeled_row(box, 10, "変化の前の枚数", ttk.Entry(box, textvariable=self.pre_var, width=8), "この枚数の正常 Wafer を流してから変化を入れます。")
        labeled_row(box, 11, "変化の後に観測する枚数", ttk.Entry(box, textvariable=self.window_var, width=8), "この枚数の中で気づかなければ「未検出」です。")

    # ------------------------------------------------------------------ 画面と設定のやりとり
    def apply_settings(self, settings: AppSettings) -> None:
        split, methods, temporal, injection = settings.split, settings.methods, settings.temporal, settings.injection
        self.normal_mode_var.set(split.normal_mode)
        self.normal_fraction_var.set(f"{split.normal_fraction_percent:g}")
        self.normal_count_var.set(str(split.normal_count))
        self.normal_until_var.set(split.normal_until)
        self.train_fraction_var.set(f"{split.train_fraction_percent:g}")
        self.min_point_rate_var.set(f"{split.min_point_rate_percent:g}")
        self.max_missing_var.set(f"{split.max_missing_percent:g}")
        self.alpha_var.set(f"{methods.alpha_percent:g}")
        self.m3s_var.set(methods.m3s)
        self.spc_group.set(methods.spc_orders)
        self.md_group.set(methods.md_orders)
        self.pca_source_group.set(methods.pca_sources)
        self.pca_ratio_group.set(methods.pca_ratios)
        self.pca_stat_group.set([s for s, on in (("t2", methods.pca_t2), ("spe", methods.pca_spe)) if on])
        self.gpr_group.set(methods.gpr_variants)
        self.or_var.set(methods.or_enabled)
        self.temporal_var.set(temporal.enabled)
        self.parameter_mode_var.set(temporal.parameter_mode)
        self.lambda_group.set(temporal.lambdas)
        self.k_group.set(temporal.ks)
        self.shewhart_var.set(temporal.include_shewhart)
        self.arl_var.set(f"{temporal.target_arl0:g}")
        self.block_var.set(str(temporal.block_length))
        self.bootstrap_var.set(str(temporal.n_bootstrap_series))
        self.single_var.set(injection.single_enabled)
        self.pattern_group.set(injection.single_patterns)
        self.single_amp_group.set(injection.single_amplitudes)
        self.replicate_var.set(str(injection.single_replicates))
        self.temporal_injection_var.set(injection.temporal_enabled)
        self.component_group.set(injection.temporal_components)
        self.profile_group.set(injection.temporal_profiles)
        self.temporal_amp_group.set(injection.temporal_amplitudes)
        self.series_var.set(str(injection.temporal_series))
        self.pre_var.set(str(injection.temporal_pre_length))
        self.window_var.set(str(injection.temporal_window))
        self.seed_var.set(str(settings.seed))
        self._or_selection = list(methods.or_members)
        self._base_selection = list(temporal.bases)
        self.methods_changed(keep_selection=False)
        self._mode_changed()
        self.update_preview()

    def _method_options(self) -> MethodOptions:
        stats = set(self.pca_stat_group.get())
        return MethodOptions(
            m3s=self.m3s_var.get(),
            spc_orders=self.spc_group.get(),
            md_orders=self.md_group.get(),
            pca_sources=self.pca_source_group.get(),
            pca_ratios=self.pca_ratio_group.get(),
            pca_t2="t2" in stats,
            pca_spe="spe" in stats,
            gpr_variants=self.gpr_group.get(),
            alpha_percent=float(self.alpha_var.get() or 1),
            or_enabled=self.or_var.get(),
            or_members=self.or_group.get(),
        )

    def collect_settings(self) -> AppSettings:
        settings = AppSettings()
        settings.data = self.app.data_tab.collect_options()
        settings.split = SplitOptions(
            normal_mode=self.normal_mode_var.get(),
            normal_fraction_percent=read_float(self.normal_fraction_var, "正常期間の割合"),
            normal_count=read_int(self.normal_count_var, "正常期間の件数"),
            normal_until=self.normal_until_var.get().strip(),
            train_fraction_percent=read_float(self.train_fraction_var, "学習に使う割合"),
            min_point_rate_percent=read_float(self.min_point_rate_var, "共通の計測点にする条件"),
            max_missing_percent=read_float(self.max_missing_var, "計測を除く欠けの割合"),
        )
        settings.methods = self._method_options()
        settings.temporal = TemporalOptions(
            enabled=self.temporal_var.get(),
            bases=self.temporal_bases.get(),
            parameter_mode=self.parameter_mode_var.get(),
            lambdas=self.lambda_group.get(),
            ks=self.k_group.get(),
            include_shewhart=self.shewhart_var.get(),
            target_arl0=read_float(self.arl_var, "ARL₀ の目標"),
            block_length=read_int(self.block_var, "ブロックの長さ"),
            n_bootstrap_series=read_int(self.bootstrap_var, "再標本化の系列数"),
        )
        settings.injection = InjectionOptions(
            single_enabled=self.single_var.get(),
            single_patterns=self.pattern_group.get(),
            single_amplitudes=self.single_amp_group.get(),
            single_replicates=read_int(self.replicate_var, "条件ごとの回数"),
            temporal_enabled=self.temporal_injection_var.get(),
            temporal_components=self.component_group.get(),
            temporal_profiles=self.profile_group.get(),
            temporal_amplitudes=self.temporal_amp_group.get(),
            temporal_series=read_int(self.series_var, "系列数"),
            temporal_pre_length=read_int(self.pre_var, "変化の前の枚数"),
            temporal_window=read_int(self.window_var, "変化の後に観測する枚数"),
        )
        settings.seed = read_int(self.seed_var, "乱数の種")
        return settings

    def methods_changed(self, keep_selection: bool = True) -> None:
        """選んだ 1 Wafer の手法に合わせて、OR 統合と経時変化の土台の選択肢を作り直す。"""
        if keep_selection:
            self._or_selection = self.or_group.get() or self._or_selection
            self._base_selection = self.temporal_bases.get() or self._base_selection
        names = selected_method_names(self._method_options())
        options = [(name, method_label(name)) for name in names]
        self.or_group.set_options(options, [n for n in self._or_selection if n in names], columns=3)
        self.temporal_bases.set_options(options, [n for n in self._base_selection if n in names], columns=3)
        self.or_group.set_state(self.or_var.get())
        self.temporal_bases.set_state(self.temporal_var.get())

    def reset_or_members(self) -> None:
        self._or_selection = list(STUDY_OR_MEMBERS)
        self.or_group.set(STUDY_OR_MEMBERS)
        missing = [m for m in STUDY_OR_MEMBERS if m not in self.or_group.variables]
        if missing:
            self.status.configure(text="推奨の手法のうち、上で選んでいないもの：" + "、".join(method_label(m) for m in missing))

    def _mode_changed(self) -> None:
        custom = self.parameter_mode_var.get() == "custom"
        self.lambda_group.set_state(custom)
        self.k_group.set_state(custom)

    def reset_defaults(self) -> None:
        self.apply_settings(AppSettings())
        self.status.configure(text="既定の値に戻しました。")

    def update_preview(self) -> None:
        prepared = self.app.prepared
        if prepared is None:
            self.preview_label.configure(text="（データを確認すると、ここに件数の見込みが出ます）")
            return
        try:
            split = SplitOptions(
                normal_mode=self.normal_mode_var.get(),
                normal_fraction_percent=read_float(self.normal_fraction_var, "正常期間の割合"),
                normal_count=read_int(self.normal_count_var, "正常期間の件数"),
                normal_until=self.normal_until_var.get().strip(),
                train_fraction_percent=read_float(self.train_fraction_var, "学習に使う割合"),
            )
            normal = normal_period_mask(prepared.measurements, split, prepared.check.has_datetime)
        except UserFacingError as error:
            self.preview_label.configure(text=f"見込み：{error.what}")
            return
        labeled = prepared.measurements["label"].to_numpy()
        usable = int(np.sum(normal & ~labeled))
        n_train = int(round(split.train_fraction_percent / 100.0 * usable))
        n_calibration = usable - n_train
        alpha = float(self.alpha_var.get() or 1) / 100.0
        text = (
            f"見込み：正常期間 {int(normal.sum()):,} 件（学習 {n_train:,}・校正 {n_calibration:,}"
            + (f"・ラベルで除外 {int(np.sum(normal & labeled)):,}" if labeled.any() else "")
            + f"）、評価 {int(np.sum(~normal)):,} 件。欠けの多い計測はこのあと除きます。"
        )
        if n_calibration * alpha < 5:
            text += f"\n校正が {n_calibration:,} 件だと、誤報率 {alpha:.1%} の管理限界は不安定です（目安 {int(np.ceil(5 / alpha)):,} 件以上）。"
        self.preview_label.configure(text=text, style="Warning.TLabel" if n_calibration * alpha < 5 else "Section.TLabel")

    # ------------------------------------------------------------------ 実行
    def set_busy(self, busy: bool) -> None:
        ready = self.app.prepared is not None
        self.run_button.state(["disabled"] if busy or not ready else ["!disabled"])
        self.defaults_button.state(["disabled"] if busy else ["!disabled"])
        if not ready:
            self.status.configure(text=NOT_READY_TEXT)
        elif self.status.cget("text") == NOT_READY_TEXT:
            self.status.configure(text="")

    def run(self) -> None:
        if self.app.prepared is None:
            return
        try:
            settings = self.collect_settings()
        except Exception as error:
            show_error(self, error)
            return
        problems = validate_settings(settings)
        if problems:
            show_error(self, UserFacingError("設定に直すところがあります。", "\n".join(f"・{p}" for p in problems), "上の項目を直してから、もう一度「検証を実行」を押してください。"))
            return
        prepared = self.app.prepared
        self.app.settings = settings
        self.status.configure(text="")

        def work(progress, cancel):
            return run_analysis(prepared, settings, progress, cancel)

        self.app.run_task("検証を実行しています", work, self.app.set_result)
