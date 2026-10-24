# -*- coding: utf-8 -*-
r"""End-to-end effect of Icraft INT8 subgraph outputs on the GLC codec.

Instead of guessing a noise model, every subgraph boundary is replaced by the
*actual* INT8 HostBackend output of the compiled subgraph, and the rate is
computed analytically with the model's own `get_y_gaussian_bits` (so no
compressai / rANS is needed).

Chain per image:

    x --S1(i8)--> y, z
    z_hat = vq(z)                      (PS-side argmin + codebook lookup)
    z_hat --S2(i8)--> params
    q_enc,q_dec,scales0,means0 = model.separate_prior(params)
    common = model.y_spatial_prior_reduction(params)
    for k in 0..3:                     k=0 uses scales0/means0 directly
        k>0: (y_hat_so_far, common) --S3_k(i8)--> scales, means
        y_res,y_q,y_hat_k,scales_hat = model.process_with_mask(...)
        bits_y += model.get_y_gaussian_bits(y_q, scales_hat).sum()
    y_hat = y_hat_so_far * q_dec
    y_hat --S4(i8)--> x_hat
    bits = bits_y + 16*16*log2(codebook_size)

Baseline is model.test(x, q) on the same image (fp32, same analytic rate).

Usage (in envs\glc):
  python quant_e2e.py --repo <GLC> --model <ckpt> --compile_root <dir>
                      --dtype int8 [--n 4] [--size 256] [--q 0]
"""
import argparse
import importlib.util
import math
import os
import re
import subprocess
import sys

import numpy as np
import torch
from PIL import Image

BIN = r"E:\fudanwei\Icraft-3.36.1\bin"

# subgraph key -> (network name, [output NHWC shapes] in Output-op order)
SPECS = {
    "s1": ("s1_encoder_ga_hyper", [(1, 16, 16, 256), (1, 4, 4, 256)]),
    "s2": ("s2_hyperdec_fusion", [(1, 16, 16, 768)]),
    "s3p1": ("s3_phase1", [(1, 16, 16, 256), (1, 16, 16, 256)]),
    "s3p2": ("s3_phase2", [(1, 16, 16, 256), (1, 16, 16, 256)]),
    "s3p3": ("s3_phase3", [(1, 16, 16, 256), (1, 16, 16, 256)]),
    "s4": ("s4_gs_generator", [(1, 256, 256, 3)]),
}


def nhwc(t):
    return np.ascontiguousarray(t.detach().cpu().numpy().transpose(0, 2, 3, 1))


def to_nchw(a):
    return torch.from_numpy(np.ascontiguousarray(a.transpose(0, 3, 1, 2)))


class Runner:
    """Runs a compiled subgraph on the HostBackend and caches its output v_ids.

    use_zg=True switches from the *quantized graph* to the **deployable
    `_ZG` artifact** produced by `icraft-generate`.  Those two are NOT
    numerically equivalent (see reports\\V4_ZG产物数值对拍报告.md), and `_ZG` is
    what the board actually loads, so any end-to-end number intended to describe
    the board must use it.
    """

    def __init__(self, root, dtype, workdir, use_zg=False, mix_root="",
                 mix_tag="", mix_keys=("s1",)):
        self.root, self.dtype, self.workdir = root, dtype, workdir
        self.use_zg = use_zg
        self.mix_root, self.mix_tag, self.mix_keys = mix_root, mix_tag, mix_keys
        self.cache = {}
        os.makedirs(workdir, exist_ok=True)

    def paths(self, key):
        name = SPECS[key][0]
        # a per-subgraph override, e.g. the S1 mixed-precision artifact
        if self.mix_root and key in self.mix_keys:
            g = os.path.join(self.mix_root, "%s_%s" % (key, self.mix_tag), "gen")
            return (os.path.join(g, "%s_ZG.json" % name),
                    os.path.join(g, "%s_ZG.raw" % name))
        d = os.path.join(self.root, "%s_%s" % (key, self.dtype))
        if self.use_zg:
            g = os.path.join(d, "gen")
            return (os.path.join(g, "%s_ZG.json" % name),
                    os.path.join(g, "%s_ZG.raw" % name))
        return (os.path.join(d, "%s_quantized.json" % name),
                os.path.join(d, "%s_quantized.raw" % name))

    def __call__(self, key, inputs, out_shapes):
        qj, qr = self.paths(key)
        run = os.path.join(self.workdir, "run_" + key)
        os.makedirs(run, exist_ok=True)
        ip = []
        for i, t in enumerate(inputs):
            p = os.path.join(run, "in%d.ftmp" % i)
            nhwc(t).astype(np.float32).tofile(p)
            ip.append(p)
        # 1st pass: learn the runtime output v_ids for this exact graph
        if key not in self.cache:
            subprocess.run([os.path.join(BIN, "icraft-run.exe"), "--json", qj,
                            "--raw", qr, "--input", ";".join(ip),
                            "--backends", "Host",
                            "--log_path", os.path.join(run, "logs"), "--log_io"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=3600)
            log = None
            for r, _d, fs in os.walk(os.path.join(run, "logs")):
                for f in fs:
                    if f.endswith("_run_io.log"):
                        log = os.path.join(r, f)
            vids = []
            if log:
                for ln in open(log, encoding="utf-8", errors="replace"):
                    if re.match(r"\s*Output\b", ln):
                        vids = [int(m) for m in re.findall(r"\((\d+)\|", ln)]
            if len(vids) != len(out_shapes):
                raise RuntimeError("%s: found %d output v_ids %s, expected %d"
                                   % (key, len(vids), vids, len(out_shapes)))
            self.cache[key] = vids
        vids = self.cache[key]
        subprocess.run([os.path.join(BIN, "icraft-run.exe"), "--json", qj,
                        "--raw", qr, "--input", ";".join(ip), "--backends", "Host",
                        "--log_path", os.path.join(run, "dump"), "--dump_format", "SFB",
                        "--dump_ftmp", ",".join(str(v) for v in vids)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=3600)
        outs = []
        for v, shp in zip(vids, out_shapes):
            fp = None
            for r, _d, fs in os.walk(os.path.join(run, "dump")):
                c = os.path.join(r, "%d.ftmp" % v)
                if os.path.exists(c):
                    fp = c
            if fp is None:
                raise RuntimeError("%s: no dump for v_id %d" % (key, v))
            outs.append(to_nchw(np.fromfile(fp, dtype=np.float32).reshape(shp)))
        return outs


def psnr(a, b):
    mse = float(((a - b) ** 2).mean())
    return 10 * math.log10(4.0 / max(mse, 1e-12))     # data range [-1,1] -> 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--compile_root", default=r"E:\fudanwei\工作区\compile2")
    ap.add_argument("--dtype", default="int8")
    ap.add_argument("--png_dir", default=r"E:\fudanwei\工作区\testset\kodak")
    ap.add_argument("--work", default=r"E:\fudanwei\工作区\e2e")
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--q", type=int, default=0)
    ap.add_argument("--icraft", default="all",
                    help="comma list of subgraphs to take from the Icraft "
                         "compiled artifacts; everything else is computed in "
                         "fp32 PyTorch. Use 's1,s2,s3p1,s3p2,s3p3' for the "
                         "edge-encoder-only architecture (S4 stays fp32).")
    ap.add_argument("--save_recon", default="",
                    help="dir to dump the fp32 and quantized reconstructions "
                         "as raw float32 (NCHW, [-1,1]) for the perceptual "
                         "metrics in V7")
    ap.add_argument("--use_zg", action="store_true",
                    help="run the deployable `gen/<name>_ZG` artifact instead of "
                         "the quantized graph (they are not numerically equal)")
    ap.add_argument("--mix_root", default="",
                    help="directory holding a mixed-precision artifact for the "
                         "subgraphs in --mix_subs (V9), e.g. 工作区\\compile_mix")
    ap.add_argument("--mix_tag", default="int8bf16")
    ap.add_argument("--mix_subs", default="s1")
    a = ap.parse_args()
    use = set(SPECS) if a.icraft == "all" else set(
        x.strip() for x in a.icraft.split(",") if x.strip())

    repo = os.path.abspath(a.repo)
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "src", "utils"))
    from src.models.image_model import GLC_Image
    from src.utils.test_utils import get_state_dict

    model = GLC_Image(inplace=True)
    model.load_state_dict(get_state_dict(a.model), strict=True)
    model.eval()

    # the exported subgraphs used the whole-block attention rewrite
    spec = importlib.util.spec_from_file_location(
        "c1exp", r"E:\fudanwei\工作区\tools\c1_export_subgraphs.py")
    exp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exp)
    exp.patch_attention_to_full(repo, model)

    R = Runner(a.compile_root, a.dtype, a.work, use_zg=a.use_zg,
               mix_root=a.mix_root, mix_tag=a.mix_tag,
               mix_keys=tuple(s.strip() for s in a.mix_subs.split(",") if s.strip()))
    if a.use_zg:
        print("backend: deployable _ZG artifacts (not the quantized graph)")
    if a.mix_root:
        print("mixed precision: %s from %s (tag %s)" %
              (a.mix_subs, a.mix_root, a.mix_tag))
    pngs = sorted(f for f in os.listdir(a.png_dir) if f.lower().endswith(".png"))
    S, L = a.size, a.size // 16
    rows = []

    for i in range(a.n):
        im = Image.open(os.path.join(a.png_dir, pngs[i % len(pngs)])).convert("RGB")
        w, h = im.size
        x0, y0 = (i * 37) % max(1, w - S), (i * 53) % max(1, h - S)
        px = np.asarray(im.crop((x0, y0, x0 + S, y0 + S)), dtype=np.float32) / 127.5 - 1.0
        x = torch.from_numpy(px.transpose(2, 0, 1)).unsqueeze(0).contiguous()

        with torch.no_grad():
            ref = model.test(x, a.q)
            bit_fp32 = ref["bit"]
            x_fp32 = ref["x_hat"].clamp(-1, 1)
            curr_q_enc = model.q_enc[a.q:a.q + 1]
            curr_q_dec = model.q_dec[a.q:a.q + 1]

            # ---- encoder side: S1 (or fp32 fallback) ----
            if "s1" in use:
                y, z = R("s1", [x], SPECS["s1"][1])
            else:
                y = model.enc(model.vqgan.encoder(x), curr_q_enc)
                z = model.hyper_enc(y)
            idx = model.z_vq.get_indices(z)
            z_hat = model.z_vq.get_quan_feat(
                idx, (z.shape[0], z.shape[2], z.shape[3], z.shape[1]))
            if "s2" in use:
                params, = R("s2", [z_hat], SPECS["s2"][1])
            else:
                params = model.y_prior_fusion(model.hyper_dec(z_hat))
            q_enc, q_dec, scales0, means0 = model.separate_prior(params)
            common = model.y_spatial_prior_reduction(params)

            masks = model.get_mask_four_parts(*y.shape, y.dtype, y.device)
            y_scaled = y * q_enc
            y_hat_so_far = torch.zeros_like(y)
            bits_y = 0.0
            for k, mask in enumerate(masks):
                if k == 0:
                    s_, m_ = scales0, means0
                elif ("s3p%d" % k) in use:
                    s_, m_ = R("s3p%d" % k, [y_hat_so_far, common],
                               SPECS["s3p%d" % k][1])
                else:
                    ad = getattr(model, "y_spatial_prior_adaptor_%d" % k)
                    s_, m_ = model.y_spatial_prior(
                        ad(torch.cat((y_hat_so_far, common), 1))).chunk(2, 1)
                _res, y_q, y_hat_k, sc_hat = model.process_with_mask(
                    y_scaled, s_, m_, mask)
                bits_y += float(model.get_y_gaussian_bits(y_q, sc_hat).sum())
                y_hat_so_far = y_hat_so_far + y_hat_k
            y_hat = y_hat_so_far * q_dec

            # ---- decoder side: S4 (or fp32 fallback) ----
            if "s4" in use:
                x_i8, = R("s4", [y_hat], SPECS["s4"][1])
            else:
                x_i8 = model.vqgan.generator(model.dec(y_hat, curr_q_dec))
            x_i8 = x_i8.clamp(-1, 1)

            # rate of the hyper latent: one codebook index per 4x4 z position
            zh, zw = z_hat.shape[-2], z_hat.shape[-1]
            bits_z = zh * zw * math.log2(model.codebook_size)
            bit_i8 = bits_y + bits_z
            n_px = S * S
            r = dict(sample=i, png=pngs[i % len(pngs)],
                     fp32_bpp=bit_fp32 / n_px, int8_bpp=bit_i8 / n_px,
                     fp32_psnr=psnr(x_fp32, x), int8_psnr=psnr(x_i8, x),
                     fp32_vs_int8_psnr=psnr(x_i8, x_fp32))
            rows.append(r)
            if a.save_recon:
                os.makedirs(a.save_recon, exist_ok=True)
                stem = os.path.splitext(r["png"])[0]
                x_i8.detach().cpu().numpy().astype(np.float32).tofile(
                    os.path.join(a.save_recon, "%s_%s.f32" % (stem, a.dtype)))
                x_fp32.detach().cpu().numpy().astype(np.float32).tofile(
                    os.path.join(a.save_recon, "%s_fp32.f32" % stem))
                x.detach().cpu().numpy().astype(np.float32).tofile(
                    os.path.join(a.save_recon, "%s_orig.f32" % stem))
            print("  %-14s fp32 bpp=%.5f PSNR=%.2f | %s bpp=%.5f PSNR=%.2f "
                  "| PSNR(%s recon vs fp32 recon)=%.2f"
                  % (r["png"], r["fp32_bpp"], r["fp32_psnr"], a.dtype,
                     r["int8_bpp"], r["int8_psnr"], a.dtype,
                     r["fp32_vs_int8_psnr"]))

    if rows:
        n = len(rows)
        print("\nMEAN over %d images: fp32 bpp=%.5f PSNR=%.2f -> %s bpp=%.5f PSNR=%.2f "
              "(dPSNR=%+.2f dB, dbpp=%+.5f, %+.1f%%)"
              % (n, sum(r["fp32_bpp"] for r in rows) / n,
                 sum(r["fp32_psnr"] for r in rows) / n, a.dtype,
                 sum(r["int8_bpp"] for r in rows) / n,
                 sum(r["int8_psnr"] for r in rows) / n,
                 sum(r["int8_psnr"] - r["fp32_psnr"] for r in rows) / n,
                 sum(r["int8_bpp"] - r["fp32_bpp"] for r in rows) / n,
                 100 * (sum(r["int8_bpp"] for r in rows) /
                        max(1e-9, sum(r["fp32_bpp"] for r in rows)) - 1)))
    import json
    json.dump(rows, open(os.path.join(a.work, "e2e_%s.json" % a.dtype), "w"), indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
