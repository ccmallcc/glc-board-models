# -*- coding: utf-8 -*-
r"""V8: figures for the report / slides.

Produces, into --out:

  quant_compare.png  original | fp32 | BF16 | INT8 reconstructions for a few
                     images, annotated with the per-image PSNR / LPIPS
  error_maps.png     |quantized - fp32| error maps, amplified, so the *kind* of
                     error INT8 introduces is visible (not just its magnitude)
  rd_curves.png      rate-distortion curves from the real bitstream (V7 data):
                     bpp vs PSNR / MS-SSIM / LPIPS / DISTS

Inputs are the raw float32 dumps produced by quant_e2e.py --save_recon and the
JSONs from v7_perceptual.py.  No model or GPU needed.

Usage (envs\glc):
  python v8_visual_compare.py --recon_dir 工作区\recon_real24 \
      --v7_recon 工作区\v7_recon\v7_recon.json \
      --v7_bits  工作区\v7_kodak\v7_bitstream.json \
      --out 工作区\v8
"""
import argparse
import json
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

# Pick a CJK-capable font so the Chinese labels are not rendered as boxes.
_cjk = None
for _name in ("Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Source Han Sans SC",
              "WenQuanYi Zen Hei", "PingFang SC", "Arial Unicode MS"):
    try:
        if any(f.name == _name for f in font_manager.fontManager.ttflist):
            _cjk = _name
            break
    except Exception:
        pass
if _cjk:
    plt.rcParams["font.sans-serif"] = [_cjk, "DejaVu Sans"]
    print("CJK font: %s" % _cjk)
else:
    print("WARNING: no CJK font found -- Chinese labels will be missing")
plt.rcParams["axes.unicode_minus"] = False


def load(path, side):
    return np.fromfile(path, dtype=np.float32).reshape(3, side, side)


def to_img(a):
    """CHW in [-1,1] -> HWC in [0,1]."""
    return np.clip((a.transpose(1, 2, 0) + 1.0) * 0.5, 0, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recon_dir", required=True)
    ap.add_argument("--v7_recon", default="")
    ap.add_argument("--v7_bits", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=4)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    stems = sorted({os.path.basename(p).rsplit("_", 1)[0]
                    for p in os.listdir(a.recon_dir) if p.endswith("_orig.f32")})
    side = int(np.sqrt(os.path.getsize(
        os.path.join(a.recon_dir, stems[0] + "_orig.f32")) // 4 // 3))
    print("found %d images, side=%d" % (len(stems), side))

    metrics = {}
    if a.v7_recon and os.path.exists(a.v7_recon):
        for r in json.load(open(a.v7_recon, encoding="utf-8")):
            metrics[(r["stem"], r["variant"])] = r

    # ---------- figure 1: reconstructions ---------------------------------
    sel = stems[::max(1, len(stems) // a.n)][:a.n]
    variants = ["orig", "fp32", "bf16", "int8"]
    titles = {"orig": "原图 (未压缩)", "fp32": "fp32 重建",
              "bf16": "BF16 量化", "int8": "INT8 量化"}
    fig, axes = plt.subplots(len(sel), len(variants),
                             figsize=(3.0 * len(variants), 3.15 * len(sel)))
    if len(sel) == 1:
        axes = axes.reshape(1, -1)
    for i, stem in enumerate(sel):
        for j, v in enumerate(variants):
            p = os.path.join(a.recon_dir, "%s_%s.f32" % (stem, v))
            ax = axes[i][j]
            if not os.path.exists(p):
                ax.axis("off"); continue
            ax.imshow(to_img(load(p, side)))
            ax.set_xticks([]); ax.set_yticks([])
            m = metrics.get((stem, v))
            if j == 0:
                ax.set_ylabel(stem, fontsize=9)
            if i == 0:
                ax.set_title(titles[v], fontsize=11)
            if m and v != "orig":
                ax.set_xlabel("PSNR %.2f dB ｜ LPIPS %.3f\nMS-SSIM %.3f ｜ DISTS %.3f"
                              % (m["psnr"], m["lpips"], m["ms_ssim"], m["dists"]),
                              fontsize=7.5)
    fig.suptitle("GLC 编码端量化对比（真 Kodak，256×256 裁剪，q0，S4 保持 fp32）",
                 fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    p1 = os.path.join(a.out, "quant_compare.png")
    fig.savefig(p1, dpi=150); plt.close(fig)
    print("-> %s" % p1)

    # ---------- figure 2: error maps, SHARED colour scale ---------------
    # Both columns must use the same vmax, otherwise the two amplification
    # factors make the panels incomparable.  vmax = 99th percentile of the
    # combined error over all shown images/variants.
    errs, fp32s = {}, {}
    pool = []
    for stem in sel:
        f = load(os.path.join(a.recon_dir, stem + "_fp32.f32"), side)
        fp32s[stem] = f
        for v in ("bf16", "int8"):
            p = os.path.join(a.recon_dir, "%s_%s.f32" % (stem, v))
            if not os.path.exists(p):
                continue
            e = np.abs(load(p, side) - f).mean(axis=0)
            errs[(stem, v)] = e
            pool.append(e.ravel())
    vmax = float(np.percentile(np.concatenate(pool), 99.0)) if pool else 1.0
    print("shared error vmax (p99) = %.4e" % vmax)

    fig, axes = plt.subplots(len(sel), 2, figsize=(7.0, 3.2 * len(sel)))
    if len(sel) == 1:
        axes = axes.reshape(1, -1)
    for i, stem in enumerate(sel):
        for j, v in enumerate(["bf16", "int8"]):
            ax = axes[i][j]
            e = errs.get((stem, v))
            if e is None:
                ax.axis("off"); continue
            im = ax.imshow(e, cmap="inferno", vmin=0, vmax=vmax)
            ax.set_xticks([]); ax.set_yticks([])
            if i == 0:
                ax.set_title("|%s − fp32|   均值 %.2e   最大 %.2e"
                             % (v.upper(), e.mean(), e.max()), fontsize=10)
            else:
                ax.set_ylabel(stem, fontsize=8)
            plt.colorbar(im, ax=ax, fraction=0.046, pad=0.02)
    fig.suptitle("量化误差的空间分布（两列共用同一色标，vmax = 全体 99 分位 = %.2e）"
                 "\n亮度 = 与 fp32 的逐像素差；BF16 误差弥散，INT8 误差集中在结构/边缘"
                 % vmax, fontsize=11)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    p2 = os.path.join(a.out, "error_maps.png")
    fig.savefig(p2, dpi=150); plt.close(fig)
    print("-> %s" % p2)

    # ---------- figure 3: RD curves ---------------------------------------
    if a.v7_bits and os.path.exists(a.v7_bits):
        rows = json.load(open(a.v7_bits, encoding="utf-8"))
        byq = {}
        for r in rows:
            byq.setdefault(r["q"], []).append(r)
        qs = sorted(byq)
        bpp = [np.mean([x["bpp"] for x in byq[q]]) for q in qs]
        fig, axes = plt.subplots(1, 4, figsize=(18, 4.0))
        for ax, key, label, better in (
                (axes[0], "psnr", "PSNR (dB) ↑", True),
                (axes[1], "ms_ssim", "MS-SSIM ↑", True),
                (axes[2], "lpips", "LPIPS ↓", False),
                (axes[3], "dists", "DISTS ↓", False)):
            y = [np.mean([x[key] for x in byq[q]]) for q in qs]
            ax.plot(bpp, y, "o-", lw=2, ms=7)
            for xi, yi, q in zip(bpp, y, qs):
                ax.annotate("q%d" % q, (xi, yi), textcoords="offset points",
                            xytext=(6, 6), fontsize=9)
            ax.set_xlabel("bpp (整包含 76 B 头)"); ax.set_ylabel(label)
            ax.grid(alpha=0.3)
            if key == "psnr":
                ax.set_xlim(0, max(bpp) * 1.25)
        fig.suptitle("GLC 真实位流 RD 曲线（真 Kodak 24 张，768×512 / 512×768）",
                     fontsize=12)
        fig.tight_layout(rect=[0, 0, 1, 0.94])
        p3 = os.path.join(a.out, "rd_curves.png")
        fig.savefig(p3, dpi=150); plt.close(fig)
        print("-> %s" % p3)

    print("\nfigures written to %s" % os.path.abspath(a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
