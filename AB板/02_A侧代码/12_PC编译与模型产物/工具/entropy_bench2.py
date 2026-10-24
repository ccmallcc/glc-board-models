#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Split the rANS cost into per-call overhead vs per-symbol cost.

Why it matters: the board's PS is a 4x Cortex-A53@1GHz, roughly an order of
magnitude slower than the i9-13980HX used for the first benchmark.  If most of
the measured 11 ms is *per-call* overhead (Python<->C++ boundary, CDF array
setup), a native C++ port on the board would be far cheaper than a naive clock
extrapolation suggests.  If it is per-symbol cost, the extrapolation stands.

Method: the four phases are entropy-coded as four separate calls of 16384
symbols each.  Concatenating them gives one call of 65536 symbols with the same
total symbol count, so the difference isolates the fixed cost per call.

Usage:
  python3 entropy_bench2.py --ops /mnt/e/.../entropy_ops [--iters 30]
"""
import argparse
import math
import os
import statistics
import time

import numpy as np
import torch
from compressai.entropy_models import GaussianConditional

SCALE_MIN, SCALE_MAX, SCALE_LEVELS = 0.11, 256.0, 64


class EM:
    def __init__(self):
        st = torch.exp(torch.linspace(math.log(SCALE_MIN), math.log(SCALE_MAX),
                                      SCALE_LEVELS))
        m = GaussianConditional(None)
        m.update_scale_table(st, force=True)
        self.model = m

    def idx(self, s):
        return self.model.build_indexes(s.clamp_min(SCALE_MIN))

    def enc(self, v, i, m):
        return self.model.compress(v, i, means=m)[0]

    def dec(self, p, i, m):
        return self.model.decompress([p], i, means=m)


def med(fn, iters, warmup=5):
    for _ in range(warmup):
        fn()
    ts = []
    for _ in range(iters):
        t0 = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t0)
    return statistics.median(ts) * 1e3      # ms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ops", required=True)
    ap.add_argument("--iters", type=int, default=30)
    a = ap.parse_args()

    V, S, M = [], [], []
    for k in range(4):
        V.append(np.load(os.path.join(a.ops, "phase%d_symbols.npy" % k)))
        S.append(np.load(os.path.join(a.ops, "phase%d_scales.npy" % k)))
        M.append(np.load(os.path.join(a.ops, "phase%d_means.npy" % k)))

    em = EM()
    sh4 = (1, 256, 16, 4)
    v4 = [torch.from_numpy(x).reshape(sh4) for x in V]
    s4 = [torch.from_numpy(x).reshape(sh4) for x in S]
    m4 = [torch.from_numpy(x).reshape(sh4) for x in M]

    with torch.no_grad():
        i4 = [em.idx(s) for s in s4]
        p4 = [em.enc(v, i, m) for v, i, m in zip(v4, i4, m4)]

        # 4 separate calls (what the codec actually does)
        def four_enc():
            for v, i, m in zip(v4, i4, m4):
                em.enc(v, i, m)
        def four_dec():
            for p, i, m in zip(p4, i4, m4):
                em.dec(p, i, m)
        def four_idx():
            for s in s4:
                em.idx(s)

        t_enc4 = med(four_enc, a.iters)
        t_dec4 = med(four_dec, a.iters)
        t_idx4 = med(four_idx, a.iters)

        # one concatenated call of the same total symbol count
        sh1 = (1, 256, 16, 16)
        v1 = torch.cat(v4, dim=3).reshape(sh1).contiguous()
        s1 = torch.cat(s4, dim=3).reshape(sh1).contiguous()
        m1 = torch.cat(m4, dim=3).reshape(sh1).contiguous()
        i1 = em.idx(s1)
        p1 = em.enc(v1, i1, m1)

        t_enc1 = med(lambda: em.enc(v1, i1, m1), a.iters)
        t_dec1 = med(lambda: em.dec(p1, i1, m1), a.iters)
        t_idx1 = med(lambda: em.idx(s1), a.iters)

    print("符号总数 65536（4 相位 x 16384）")
    print()
    print("%-26s %10s %10s %10s" % ("", "4 次调用", "1 次调用", "差值"))
    print("%-26s %10.3f %10.3f %10.3f" % ("build_indexes (ms)", t_idx4, t_idx1, t_idx4 - t_idx1))
    print("%-26s %10.3f %10.3f %10.3f" % ("AE 编码 (ms)", t_enc4, t_enc1, t_enc4 - t_enc1))
    print("%-26s %10.3f %10.3f %10.3f" % ("AD 解码 (ms)", t_dec4, t_dec1, t_dec4 - t_dec1))
    print()
    print("→ 若 4 次调用明显慢于 1 次，说明存在固定的**每次调用开销**，")
    print("  这部分在板端原生 C++（无 Python<->C++ 边界）里会消失。")
    print()
    print("每符号成本（按 1 次调用，剔除调用开销）:")
    print("  AE %.2f ns/symbol   AD %.2f ns/symbol"
          % (t_enc1 * 1e6 / 65536, t_dec1 * 1e6 / 65536))
    print("每调用固定开销（= 4 次调用总时间 - 1 次调用时间, 除以 3）:")
    print("  AE %.3f ms   AD %.3f ms   build_indexes %.3f ms"
          % ((t_enc4 - t_enc1) / 3, (t_dec4 - t_dec1) / 3, (t_idx4 - t_idx1) / 3))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
