"""スライドに載せる数式を PNG 画像にする（matplotlib の mathtext を使用）。

画像は「指定したポイント数の文字サイズ」で描き、formulas/formulas.json にインチ単位の幅・高さを書き出す。
スライド側はその寸法のまま配置する。PowerPoint の数式機能は使わない。
使い方: ../../.venv/bin/python render_formulas.py
"""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from PIL import Image  # noqa: E402

OUTPUT_DIR = Path(__file__).with_name("formulas")
DPI = 300
PAD_INCH = 0.04
INK_COLOR = "#1E1C33"
WHITE_COLOR = "#FFFFFF"

plt.rcParams["mathtext.fontset"] = "stix"
plt.rcParams["font.family"] = "STIXGeneral"

# key: (数式, 文字サイズpt)
FORMULAS = {
    "m3s": (r"$\mathrm{M3S} = |\,\bar{z}\,| + 3\,s$", 22),
    "zernike": (r"$f_x(x,y) = \sum_{k=1}^{36} a_k Z_k(x,y),\qquad f_y(x,y) = \sum_{k=1}^{36} b_k Z_k(x,y)$", 18),
    "ar1": (r"$\boldsymbol{\beta}_t - \boldsymbol{\mu} = \rho\,(\boldsymbol{\beta}_{t-1} - \boldsymbol{\mu}) + \boldsymbol{\eta}_t,\quad \boldsymbol{\eta}_t \sim N(0,\,(1-\rho^2)\,\Sigma_\beta)$", 17),
    "sigma_dir": (r"$\sigma_{\mathrm{dir}} = \sqrt{\mathbf{d}^{\top}\Sigma_z\,\mathbf{d}},\qquad \Delta = a\,\sigma_{\mathrm{dir}}\,\mathbf{d}$", 20),
    "md": (r"$D^2 = (\boldsymbol{\beta} - \boldsymbol{\mu})^{\top}\,\Sigma^{-1}\,(\boldsymbol{\beta} - \boldsymbol{\mu})$", 18),
    "t2": (r"$T^2 = \sum_{k \leq K} t_k^2 / \lambda_k$", 18),
    "spe": (r"$\mathrm{SPE} = \|\,\mathbf{z} - \hat{\mathbf{z}}\,\|^2$", 18),
    "gpr": (r"$z_w(s) = \mu(s) + u_w(s) + \varepsilon_w(s)$", 18),
    "ewma": (r"$S_t = \lambda\, x_t + (1 - \lambda)\, S_{t-1}$", 18),
    "cusum": (r"$C_t^{+} = \max(0,\ C_{t-1}^{+} + z_t - k)$", 18),
    "rmst": (r"$\mathrm{RMST} = E\,[\,\min(D,\ 200)\,]$", 18),
    "apc": (r"$\mathbf{r} = (\mathbf{f}_O + \boldsymbol{\varepsilon}_O) - X_O\,\hat{\mathbf{c}},\qquad \hat{\mathbf{c}} = \arg\min_{\mathbf{c}} \|\,\mathbf{y}_A - X_A\mathbf{c}\,\|^2$", 17),
    "b10": (r"$\Delta = t\,\mathbf{u} - s\,\mathbf{c}_s,\qquad \|\,\mathbf{c} + \Delta\,\| = \|\,\mathbf{c}\,\|$", 18),
    "m3s_white": (r"$\mathrm{M3S} = |\,\bar{z}\,| + 3\,s$", 20),
}
WHITE_KEYS = {"m3s_white"}


def render(key, tex, size_pt, color):
    fig = plt.figure(figsize=(0.01, 0.01))
    fig.text(0, 0, tex, fontsize=size_pt, color=color)
    path = OUTPUT_DIR / f"{key}.png"
    fig.savefig(path, dpi=DPI, transparent=True, bbox_inches="tight", pad_inches=PAD_INCH)
    plt.close(fig)
    with Image.open(path) as image:
        width_px, height_px = image.size
    return {"file": path.name, "w": width_px / DPI, "h": height_px / DPI}


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    sizes = {}
    for key, (tex, size_pt) in FORMULAS.items():
        sizes[key] = render(key, tex, size_pt, WHITE_COLOR if key in WHITE_KEYS else INK_COLOR)
    (OUTPUT_DIR / "formulas.json").write_text(json.dumps(sizes, indent=2), encoding="utf-8")
    for key, info in sizes.items():
        print(f"{key:12s} {info['w']:.2f} x {info['h']:.2f} in")


if __name__ == "__main__":
    main()
