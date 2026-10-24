# -*- coding: utf-8 -*-
r"""Dump the real per-phase entropy-coding operands so the AD/AE cost can be
measured in another environment (WSL, where compressai can be built).

For each of the four phases we write exactly what the codec hands to
`GaussianConditional.compress / decompress`:

    phase{k}_symbols.npy  the FULL y_scaled at the masked positions
    phase{k}_scales.npy   the per-symbol scale (sigma), compacted, >= 0.11
    phase{k}_means.npy    the per-symbol mean, compacted
    z_indices.npy         the 16 z codebook indices

⚠️ `symbols` must be the FULL value, not the residual:
   compressai's `GaussianConditional.compress(x, indexes, means)` computes
   `round(x - means)` internally.  Passing the already mean-subtracted
   residual would subtract the mean twice and inflate the bitstream ~12x
   (132 B -> 1596 B).  Sanity check: the residual range must be about [-2, 2].

Usage (in envs\glc):
  python dump_entropy_operands.py --repo <GLC> --model <ckpt>
       --out E:\fudanwei\工作区\entropy_ops [--n 4] [--size 256] [--q 0]
"""
import argparse
import os
import sys

import numpy as np
import torch
from PIL import Image

SCALE_MIN = 0.11
Z_INDEX_BITS = 14


def dump_one(model, x, q, out, S):
    """Run the full encoder path for one image and dump the entropy operands."""
    os.makedirs(out, exist_ok=True)
    with torch.no_grad():
        y = model.enc(model.vqgan.encoder(x), model.q_enc[q:q + 1])
        z = model.hyper_enc(y)
        idx = model.z_vq.get_indices(z)
        z_hat = model.z_vq.get_quan_feat(
            idx, (z.shape[0], z.shape[2], z.shape[3], z.shape[1]))
        params = model.y_prior_fusion(model.hyper_dec(z_hat))
        q_enc, q_dec, scales0, means0 = model.separate_prior(params)
        common = model.y_spatial_prior_reduction(params)
        masks = model.get_mask_four_parts(*y.shape, y.dtype, y.device)
        y_scaled = y * q_enc
        y_hat = torch.zeros_like(y)

        total_sym = 0
        for k, mk in enumerate(masks):
            if k == 0:
                s_, m_ = scales0, means0
            else:
                ad = getattr(model, "y_spatial_prior_adaptor_%d" % k)
                s_, m_ = model.y_spatial_prior(
                    ad(torch.cat((y_hat, common), 1))).chunk(2, 1)
            _r, y_q, yk, sc = model.process_with_mask(y_scaled, s_, m_, mk)
            y_hat = y_hat + yk

            sel = mk.bool().expand_as(y_scaled)
            sym = y_scaled[sel].numpy().astype(np.float32)      # FULL values
            scl = sc[sel].clamp_min(SCALE_MIN).numpy().astype(np.float32)
            mns = (m_ * mk)[sel].numpy().astype(np.float32)     # means_hat
            np.save(os.path.join(out, "phase%d_symbols.npy" % k), sym)
            np.save(os.path.join(out, "phase%d_scales.npy" % k), scl)
            np.save(os.path.join(out, "phase%d_means.npy" % k), mns)
            res = np.round(sym - mns)
            print("    phase %d: %d symbols  residual[%.0f, %.0f]"
                  % (k, sym.size, res.min(), res.max()))
            total_sym += sym.size

        zidx = idx.reshape(-1).numpy().astype(np.int64)
        np.save(os.path.join(out, "z_indices.npy"), zidx)
        np.save(os.path.join(out, "meta.npy"),
                np.array([S, q, total_sym, zidx.size], dtype=np.int64))
        print("    y 符号 %d ; z 索引 %d ; 头 %d B ; z 段 %d B"
              % (total_sym, zidx.size, 44, (zidx.size * Z_INDEX_BITS + 7) // 8))
    return total_sym, int(zidx.size)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", default=r"E:\fudanwei\工作区\entropy_ops")
    ap.add_argument("--png_dir", default=r"E:\fudanwei\工作区\testset\kodak")
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--q", type=int, default=0)
    ap.add_argument("--n", type=int, default=1,
                    help="图片数；>1 时写成 img{i}/ 子目录，便于统计整包的"
                         "真实码流大小（含 44 字节固定头）")
    a = ap.parse_args()

    repo = os.path.abspath(a.repo)
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "src", "utils"))
    from src.models.image_model import GLC_Image
    from src.utils.test_utils import get_state_dict

    model = GLC_Image(inplace=True)
    model.load_state_dict(get_state_dict(a.model), strict=True)
    model.eval()

    pngs = sorted(f for f in os.listdir(a.png_dir) if f.lower().endswith(".png"))
    S = a.size
    os.makedirs(a.out, exist_ok=True)

    for i in range(a.n):
        out = a.out if a.n == 1 else os.path.join(a.out, "img%d" % i)
        im = Image.open(os.path.join(a.png_dir, pngs[i % len(pngs)])).convert("RGB")
        w, h = im.size
        x0, y0 = (i * 37) % max(1, w - S), (i * 53) % max(1, h - S)
        px = np.asarray(im.crop((x0, y0, x0 + S, y0 + S)), dtype=np.float32) / 127.5 - 1.0
        x = torch.from_numpy(px.transpose(2, 0, 1)).unsqueeze(0).contiguous()
        print("=== img%d  %s crop(%d,%d) ===" % (i, pngs[i % len(pngs)], x0, y0))
        dump_one(model, x, a.q, out, S)

    print("\n  -> %s" % os.path.abspath(a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
