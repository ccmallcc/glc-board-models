# -*- coding: utf-8 -*-
r"""Timing of the edge-encoder / PC-decoder split on the PC GPU.

For the "board only compresses, PC decompresses and displays" architecture the
question is: how fast can the PC side run?  This measures, on the real GPU:

  encoder side : VQGAN encoder + enc + hyper_enc + VQ-E + hyper_dec +
                 y_prior_fusion + 3x (adaptor + y_spatial_prior) + AE bookkeeping
  decoder side : VQ-D + hyper_dec + y_prior_fusion + 3x prior + gs + generator

Usage (in envs\glc):
  python split_timing.py --repo <GLC> --model <ckpt> [--size 256]
                         [--q 0] [--iters 10] [--warmup 3] [--cpu]
"""
import argparse
import os
import sys
import time

import numpy as np
import torch


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--q", type=int, default=0)
    ap.add_argument("--iters", type=int, default=10)
    ap.add_argument("--warmup", type=int, default=3)
    ap.add_argument("--cpu", action="store_true")
    a = ap.parse_args()

    repo = os.path.abspath(a.repo)
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "src", "utils"))
    from src.models.image_model import GLC_Image
    from src.utils.test_utils import get_state_dict

    dev = torch.device("cpu" if a.cpu else "cuda")
    if not a.cpu and not torch.cuda.is_available():
        print("CUDA unavailable, falling back to CPU")
        dev = torch.device("cpu")
    model = GLC_Image(inplace=True)
    model.load_state_dict(get_state_dict(a.model), strict=True)
    model.to(dev).eval()
    print("device: %s%s" % (dev, (" (" + torch.cuda.get_device_name(0) + ")")
                            if dev.type == "cuda" else ""))

    x = torch.randn(1, 3, a.size, a.size, device=dev)
    q = a.q
    S, L = a.size, a.size // 16

    def encode():
        """Board-side work (weights all on the accelerator)."""
        with torch.no_grad():
            y = model.enc(model.vqgan.encoder(x), model.q_enc[q:q + 1])
            z = model.hyper_enc(y)
            idx = model.z_vq.get_indices(z)
            z_hat = model.z_vq.get_quan_feat(
                idx, (z.shape[0], z.shape[2], z.shape[3], z.shape[1]))
            params = model.y_prior_fusion(model.hyper_dec(z_hat))
            q_enc_, q_dec_, sc0, mn0 = model.separate_prior(params)
            common = model.y_spatial_prior_reduction(params)
            masks = model.get_mask_four_parts(*y.shape, y.dtype, y.device)
            y_scaled = y * q_enc_
            y_hat = torch.zeros_like(y)
            nbits = 0.0
            for k, mk in enumerate(masks):
                if k == 0:
                    s_, m_ = sc0, mn0
                else:
                    ad = getattr(model, "y_spatial_prior_adaptor_%d" % k)
                    s_, m_ = model.y_spatial_prior(
                        ad(torch.cat((y_hat, common), 1))).chunk(2, 1)
                _r, y_q, yk, sc = model.process_with_mask(y_scaled, s_, m_, mk)
                nbits += float(model.get_y_gaussian_bits(y_q, sc).sum())
                y_hat = y_hat + yk
            return y_hat * q_dec_, idx, nbits

    def decode(y_hat):
        """PC-side work after entropy decoding."""
        with torch.no_grad():
            return model.vqgan.generator(model.dec(y_hat, model.q_dec[q:q + 1]))

    def bench(fn, *args):
        for _ in range(a.warmup):
            fn(*args)
        if dev.type == "cuda":
            torch.cuda.synchronize()
        t0 = time.time()
        for _ in range(a.iters):
            out = fn(*args)
        if dev.type == "cuda":
            torch.cuda.synchronize()
        return (time.time() - t0) / a.iters, out

    t_enc, (y_hat, idx, nbits) = bench(encode)
    t_dec, x_hat = bench(decode, y_hat)
    t_full, _ = bench(lambda: torch.no_grad()(model.test)(x, q))

    n_px = S * S
    bits = nbits + (L // 4) * (L // 4) * np.log2(model.codebook_size)
    print("\n=== %d x %d, q=%d ===" % (S, S, q))
    print("  编码端（开发板要做的那部分）: %.4f s  (%.1f fps)" % (t_enc, 1 / t_enc))
    print("  解码端（PC 要做的那部分）    : %.4f s  (%.1f fps)" % (t_dec, 1 / t_dec))
    print("  整链路串行                   : %.4f s  (%.1f fps)"
          % (t_enc + t_dec, 1 / (t_enc + t_dec)))
    print("  参考 model.test() 全程       : %.4f s" % t_full)
    print("  解码/编码 时间比             : %.2f" % (t_dec / t_enc))
    print("  码率（解析式估计）           : %.5f bpp  (%.0f B/张)"
          % (bits / n_px, bits / 8))
    print("\n  说明：这里的'编码端'含 VQ 与四相位记账（但在真实部署里 VQ 与熵编码在 PS CPU 上，"
          "不在 GPU/NPU 上）；GPU 上的这部分只代表 NPU 需要承担的网络前向。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
