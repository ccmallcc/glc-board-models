#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Measure the real AE/AD (entropy encode/decode) cost of the GLC codec.

Runs inside WSL because `compressai` needs to be built from source (no Windows
wheels).  It consumes the operands dumped on the Windows side by
`dump_entropy_operands.py`, so it does NOT need the GLC repo or the 667 MB
checkpoint -- it rebuilds exactly the workload that
`entropy_encode_stage` / `entropy_decode_stage` hand to
`GaussianConditional.compress / decompress`.

Reproduces the team's wrapper verbatim:
    scale_table = exp(linspace(log(0.11), log(256), 64))
    GaussianConditional(None).update_scale_table(scale_table, force=True)
    compact shape = (1, C, H, W//4)

Usage:
  python3 entropy_bench.py --ops /mnt/e/fudanwei/工作区/entropy_ops [--iters 20]
"""
import argparse
import json
import math
import os
import statistics
import sys
import time

import numpy as np
import torch
from compressai.entropy_models import GaussianConditional

SCALE_MIN, SCALE_MAX, SCALE_LEVELS = 0.11, 256.0, 64
Z_INDEX_BITS = 14


class ELICGaussianConditional:
    """Verbatim copy of the team's wrapper (test_image_complement2.py)."""

    def __init__(self, device):
        scale_table = torch.exp(
            torch.linspace(math.log(SCALE_MIN), math.log(SCALE_MAX), SCALE_LEVELS))
        model = GaussianConditional(None)
        model.update_scale_table(scale_table, force=True)
        self.model = model.to(device)

    def build_indexes(self, scales):
        return self.model.build_indexes(scales.clamp_min(SCALE_MIN))

    def compress(self, values, indexes, means):
        strings = self.model.compress(values, indexes, means=means)
        if len(strings) != 1:
            raise ValueError("The GLC bitstream codec requires batch size 1")
        reconstructed = torch.round(values - means) + means
        return strings[0], reconstructed

    def decompress(self, payload, indexes, means):
        return self.model.decompress([payload], indexes, means=means)


def timed(fn, iters, warmup=3):
    for _ in range(warmup):
        fn()
    ts = []
    for _ in range(iters):
        t0 = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t0)
    return statistics.median(ts), min(ts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ops", required=True)
    ap.add_argument("--iters", type=int, default=20)
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    meta = np.load(os.path.join(a.ops, "meta.npy"))
    S, q, total_sym, n_z = (int(v) for v in meta)
    print("input %dx%d  q=%d  y symbols=%d  z indices=%d"
          % (S, S, q, total_sym, n_z))
    print("torch %s  compressai %s  device=cpu"
          % (torch.__version__, __import__("compressai").__version__))

    C, L = 256, S // 16
    shape = (1, C, L, L // 4)          # exactly compact_masked()'s output shape
    em = ELICGaussianConditional(torch.device("cpu"))

    per_phase = []
    tot_idx = tot_enc = tot_dec = 0.0
    tot_bytes = 0

    for k in range(4):
        sym = np.load(os.path.join(a.ops, "phase%d_symbols.npy" % k))
        scl = np.load(os.path.join(a.ops, "phase%d_scales.npy" % k))
        mns = np.load(os.path.join(a.ops, "phase%d_means.npy" % k))
        values = torch.from_numpy(sym).reshape(shape)
        scales = torch.from_numpy(scl).reshape(shape)
        means = torch.from_numpy(mns).reshape(shape)

        with torch.no_grad():
            indexes = em.build_indexes(scales)
            payload, _recon = em.compress(values, indexes, means=means)
            decoded = em.decompress(payload, indexes, means=means)
            ok = bool(torch.equal(decoded, torch.round(values - means) + means))

            t_idx, _ = timed(lambda: em.build_indexes(scales), a.iters)
            t_enc, _ = timed(lambda: em.compress(values, indexes, means=means), a.iters)
            t_dec, _ = timed(lambda: em.decompress(payload, indexes, means), a.iters)

        nbytes = len(payload)
        tot_idx += t_idx
        tot_enc += t_enc
        tot_dec += t_dec
        tot_bytes += nbytes
        per_phase.append(dict(phase=k, symbols=int(values.numel()),
                              bytes=nbytes, idx_ms=t_idx * 1e3,
                              enc_ms=t_enc * 1e3, dec_ms=t_dec * 1e3,
                              roundtrip_ok=ok))
        print("  phase %d: %6d sym  %5d B  build_indexes %6.2f ms  AE %6.2f ms  AD %6.2f ms  roundtrip=%s"
              % (k, values.numel(), nbytes, t_idx * 1e3, t_enc * 1e3, t_dec * 1e3,
                 "OK" if ok else "FAIL"))

    z_bytes = (n_z * Z_INDEX_BITS + 7) // 8
    header = 44
    total = header + z_bytes + tot_bytes
    npx = S * S

    print("\n=== 汇总（256x256，CPU 单线程，compressai rANS 实测）===")
    print("  build_indexes（纯 torch，两端都要）: %7.2f ms" % (tot_idx * 1e3))
    print("  AE 算术编码（开发板侧）             : %7.2f ms" % (tot_enc * 1e3))
    print("  AD 算术解码（PC 侧）               : %7.2f ms" % (tot_dec * 1e3))
    print("  熵编码往返合计                     : %7.2f ms" % ((tot_enc + tot_dec) * 1e3))
    print("  码流实际大小: y %d B + z %d B + header %d B = %d B  (%.5f bpp)"
          % (tot_bytes, z_bytes, header, total, total * 8.0 / npx))
    print("  AD 吞吐: %.2f M symbols/s" % (total_sym / tot_dec / 1e6))

    out = dict(size=S, q=q, y_symbols=total_sym, z_indices=n_z,
               build_indexes_ms=tot_idx * 1e3, ae_ms=tot_enc * 1e3,
               ad_ms=tot_dec * 1e3, y_bytes=tot_bytes, z_bytes=z_bytes,
               header_bytes=header, total_bytes=total, bpp=total * 8.0 / npx,
               ad_million_symbols_per_s=total_sym / tot_dec / 1e6,
               per_phase=per_phase)
    if a.json:
        json.dump(out, open(a.json, "w"), indent=2)
        print("  -> " + a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
