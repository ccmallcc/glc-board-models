# -*- coding: utf-8 -*-
r"""V7: perceptual metrics (LPIPS-Alex, DISTS, MS-SSIM) for the GLC variants.

The project's whole pitch is *perceptual* quality, yet every number we had was
PSNR.  This script fills that gap in two modes:

  --mode bitstream   run the REAL bitstream pipeline (test_image_complement2)
                     over Kodak x q0..q3 and score the reconstructions.
  --mode recon       score reconstructions previously dumped as raw float32
                     NCHW in [-1,1] by quant_e2e.py --save_recon
                     (expects <stem>_orig.f32 plus one <stem>_<variant>.f32 each)

Metrics:
  PSNR      computed here (on [-1,1], peak-to-peak 2)
  MS-SSIM   pytorch_msssim (data_range=2)
  LPIPS     torchmetrics.image.lpip, net='alex'
  DISTS     torchmetrics.image.dists.DeepImageStructureAndTextureSimilarity

A built-in self-test asserts LPIPS/DISTS(x, x) == 0 before measuring anything,
so a broken metric setup cannot silently produce plausible-looking numbers.

Usage (WSL, needs model + compressai for bitstream mode):
  python v7_perceptual.py --mode bitstream --model_path <ckpt> \
      --input_path <kodak> --out <dir> --q 0 1 2 3
"""
import argparse
import csv
import glob
import json
import math
import os
import sys
import types

import numpy as np
import torch
import torch.nn.functional as F


def psnr(a, b, peak=2.0):
    mse = float(((a - b) ** 2).mean())
    return 99.0 if mse == 0 else 10.0 * math.log10(peak * peak / mse)


class Metrics:
    """Perceptual metrics with an explicit, *enforced* input convention.

    Value ranges are a classic silent-error source here:
      * LPIPS(normalize=True)  expects [0,1] and RAISES otherwise (we rely on
        that check), whereas LPIPS(normalize=False) silently accepts both
        [0,1] and [-1,1] and just returns a different number.
      * torchmetrics DISTS takes no `normalize` kwarg at all and expects [0,1].
      * pytorch_msssim is told data_range=2.0 and gets [-1,1].

    So: everything internal is [-1,1] (matching the model), and the metrics that
    want [0,1] get (x+1)/2.
    """

    def __init__(self, device):
        self.device = device
        self.m = {}
        try:
            from pytorch_msssim import ms_ssim
            self.m["ms_ssim"] = ms_ssim
        except Exception as e:
            print("  [warn] MS-SSIM unavailable: %s" % e)
        try:
            from torchmetrics.image.lpip import (
                LearnedPerceptualImagePatchSimilarity)
            self.m["lpips"] = LearnedPerceptualImagePatchSimilarity(
                net_type="alex", normalize=True).to(device).eval()
        except Exception as e:
            print("  [warn] LPIPS unavailable: %s" % e)
        try:
            from torchmetrics.image.dists import (
                DeepImageStructureAndTextureSimilarity)
            self.m["dists"] = DeepImageStructureAndTextureSimilarity().to(device).eval()
        except Exception as e:
            print("  [warn] DISTS unavailable: %s" % e)

    @staticmethod
    def _01(x):
        """[-1,1] -> [0,1], with a hard range check."""
        y = (x + 1.0) * 0.5
        if float(y.min()) < -1e-4 or float(y.max()) > 1.0 + 1e-4:
            raise ValueError("input outside [-1,1]: [%.4f, %.4f]"
                             % (float(x.min()), float(x.max())))
        return y.clamp(0.0, 1.0)

    @torch.no_grad()
    def self_test(self):
        """Both directions: identical inputs must be 0, and a genuinely
        different image must give a clearly non-zero value (otherwise the
        metric could be degenerate and still pass x==x)."""
        # 256x256: MS-SSIM needs >160 px (4 downsamplings), so a 64px self-test
        # would fail for the wrong reason.
        x = torch.rand(1, 3, 256, 256, device=self.device) * 2 - 1
        # a genuinely different image that is still a valid [-1,1] tensor:
        # shift the content by half a frame (NOT 1-x, which leaves the range)
        y = torch.roll(x, x.shape[-1] // 2, dims=-1)
        bad = []
        for k in ("lpips", "dists"):
            if k not in self.m:
                continue
            a = float(self.m[k](self._01(x), self._01(x)).item())
            b = float(self.m[k](self._01(x), self._01(y)).item())
            ok = (a < 1e-4) and (b > 1e-3)
            print("  self-test %-6s  same=%.3e  different=%.4f  %s"
                  % (k, a, b, "OK" if ok else "BAD"))
            if not ok:
                bad.append(k)
        if "ms_ssim" in self.m:
            a = float(self.m["ms_ssim"](x, x, data_range=2.0).item())
            b = float(self.m["ms_ssim"](x, y, data_range=2.0).item())
            ok = (a > 0.999) and (b < 0.99)
            print("  self-test ms_ssim same=%.6f  different=%.6f  %s"
                  % (a, b, "OK" if ok else "BAD"))
            if not ok:
                bad.append("ms_ssim")
        return bad

    @torch.no_grad()
    def score(self, x_hat, x):
        """x_hat, x: (1,3,H,W) in [-1,1] on self.device."""
        r = {"psnr": psnr(x_hat, x)}
        if "ms_ssim" in self.m:
            r["ms_ssim"] = float(self.m["ms_ssim"](x_hat, x, data_range=2.0).item())
        if "lpips" in self.m:
            r["lpips"] = float(self.m["lpips"](self._01(x_hat), self._01(x)).item())
        if "dists" in self.m:
            r["dists"] = float(self.m["dists"](self._01(x_hat), self._01(x)).item())
        return r


def load_raw(path, shape=None):
    a = np.fromfile(path, dtype=np.float32)
    if shape:
        a = a.reshape(shape)
    return a


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["bitstream", "recon"], required=True)
    ap.add_argument("--repo", default=r"E:\fudanwei\工作区\GLC-main\GLC-main")
    ap.add_argument("--model_path", default="")
    ap.add_argument("--input_path", default="")
    ap.add_argument("--recon_dir", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--q", type=int, nargs="+", default=[0, 1, 2, 3])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--device", default="cuda")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    dev = torch.device(a.device if torch.cuda.is_available() else "cpu")
    M = Metrics(dev)
    print("metrics available: %s" % sorted(M.m))
    bad = M.self_test()
    if bad:
        print("  !! self-test FAILED for %s -- refusing to report numbers" % bad)
        return 3

    if a.mode == "recon":
        return run_recon(a, M, dev)
    return run_bitstream(a, M, dev)


def run_recon(a, M, dev):
    stems = sorted({os.path.basename(p).rsplit("_", 1)[0]
                    for p in glob.glob(os.path.join(a.recon_dir, "*_orig.f32"))})
    if not stems:
        print("no *_orig.f32 in %s" % a.recon_dir)
        return 2
    variants = sorted({os.path.basename(p).rsplit("_", 1)[1][:-4]
                       for p in glob.glob(os.path.join(a.recon_dir, "*.f32"))}
                      - {"orig"})
    print("found %d stems, variants: %s" % (len(stems), variants))
    rows = []
    for stem in stems:
        op = os.path.join(a.recon_dir, stem + "_orig.f32")
        n = os.path.getsize(op) // 4
        side = int(math.isqrt(n // 3))
        if side * side * 3 != n:
            print("  [skip] %s: %d floats is not 3*side^2 (non-square image?)"
                  % (stem, n))
            continue
        o = torch.from_numpy(load_raw(op)).reshape(1, 3, side, side).to(dev)
        for v in variants:
            p = os.path.join(a.recon_dir, "%s_%s.f32" % (stem, v))
            if not os.path.exists(p):
                continue
            if os.path.getsize(p) != os.path.getsize(op):
                print("  [skip] %s/%s: size mismatch" % (stem, v))
                continue
            xh = torch.from_numpy(load_raw(p)).reshape(1, 3, side, side).to(dev)
            r = M.score(xh, o)
            r.update(stem=stem, variant=v, side=side)
            rows.append(r)
            print("  %-10s %-8s %4dpx  %s" % (stem, v, side,
                  "  ".join("%s=%.4f" % (k, r[k]) for k in
                            ("psnr", "ms_ssim", "lpips", "dists") if k in r)))
    if not rows:
        print("no comparable pairs found")
        return 2
    json.dump(rows, open(os.path.join(a.out, "v7_recon.json"), "w",
                         encoding="utf-8"), ensure_ascii=False, indent=2)
    print("  -> %s" % os.path.join(a.out, "v7_recon.json"))
    return 0


def run_bitstream(a, M, dev):
    repo = os.path.abspath(a.repo)
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "src", "utils"))
    stub = types.ModuleType("src.utils.metric_image")
    stub.evaluate_quality = lambda *x, **k: None
    sys.modules["src.utils.metric_image"] = stub

    from torch.utils.data import DataLoader
    import test_image_complement2 as T
    from src.models.image_model import GLC_Image
    from src.utils.test_utils import (
        OnlyImageFolder, from_0_1_to_minus1_1, get_state_dict, init_func,
    )

    init_func()
    model = GLC_Image(inplace=True).to(dev)
    model.load_state_dict(get_state_dict(a.model_path), strict=True)
    model.eval()
    em = T.build_entropy_model(dev)

    ds = OnlyImageFolder(a.input_path, padding_size=64)
    loader = DataLoader(ds, batch_size=1, num_workers=0, shuffle=False)
    n_img = len(ds) if a.limit <= 0 else min(a.limit, len(ds))

    rows = []
    for q in a.q:
        for i, (image, image_path) in enumerate(loader):
            if i >= n_img:
                break
            x = from_0_1_to_minus1_1(image.to(dev))
            height, width = x.shape[-2:]
            padding = GLC_Image.get_padding_size(height, width, 64)
            x_padded = F.pad(x, padding, mode="replicate")
            with torch.no_grad():
                container, _ = T.compress_glc(model, em, x_padded, q, (height, width))
                x_hat, _ = T.decompress_glc(model, em, container)
            name = os.path.splitext(os.path.basename(image_path[0]))[0]
            r = M.score(x_hat, x)
            r.update(q=q, image=name, h=height, w=width,
                     bytes=len(container),
                     bpp=len(container) * 8.0 / (height * width),
                     y_bytes=sum(len(s) for s in T.parse_bitstream(container)[2][1:]),
                     z_bytes=len(T.parse_bitstream(container)[2][0]))
            rows.append(r)
            print("[q%d %2d/%2d %-9s] bpp=%.5f  %s"
                  % (q, i + 1, n_img, name, r["bpp"],
                     "  ".join("%s=%.4f" % (k, r[k]) for k in
                               ("psnr", "ms_ssim", "lpips", "dists") if k in r)))
        g = [r for r in rows if r["q"] == q]
        print("  AVERAGE q%d (%d imgs): bpp=%.5f  %s"
              % (q, len(g), sum(r["bpp"] for r in g) / len(g),
                 "  ".join("%s=%.4f" % (k, sum(r[k] for r in g) / len(g))
                           for k in ("psnr", "ms_ssim", "lpips", "dists")
                           if k in g[0])))

    json.dump(rows, open(os.path.join(a.out, "v7_bitstream.json"), "w",
                         encoding="utf-8"), ensure_ascii=False, indent=2)
    cols = list(rows[0].keys())
    with open(os.path.join(a.out, "v7_bitstream.csv"), "w", newline="",
              encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print("  -> %s" % os.path.join(a.out, "v7_bitstream.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
