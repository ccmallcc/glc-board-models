#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Aggregate the real GLC2 container size and AE/AD cost over N images.

Runs in WSL (compressai).  Reads the per-image operand dirs written by
dump_entropy_operands.py --n N, and reports for each image:
    y payload bytes (4 rANS streams) + z 28 B + header 44 B = container bytes
plus the mean bpp over the set, so public material can quote one consistent
number instead of mixing an analytic estimate with a single-image measurement.

Usage:
  python3 entropy_multi.py --root /mnt/e/.../entropy_ops [--iters 10]
"""
import argparse
import json
import math
import os
import statistics
import time

import numpy as np
import torch
from compressai.entropy_models import GaussianConditional

SCALE_MIN, SCALE_MAX, SCALE_LEVELS = 0.11, 256.0, 64
Z_INDEX_BITS, HEADER = 14, 44


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


def med(fn, iters, warmup=3):
    for _ in range(warmup):
        fn()
    ts = []
    for _ in range(iters):
        t0 = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t0)
    return statistics.median(ts) * 1e3


def run_one(d, em, iters):
    meta = np.load(os.path.join(d, "meta.npy"))
    S, q, total_sym, n_z = (int(v) for v in meta)
    sh = (1, 256, 16, 4)
    vs, ss, ms = [], [], []
    for k in range(4):
        vs.append(torch.from_numpy(np.load(os.path.join(d, "phase%d_symbols.npy" % k))).reshape(sh))
        ss.append(torch.from_numpy(np.load(os.path.join(d, "phase%d_scales.npy" % k))).reshape(sh))
        ms.append(torch.from_numpy(np.load(os.path.join(d, "phase%d_means.npy" % k))).reshape(sh))
    with torch.no_grad():
        i4 = [em.idx(s) for s in ss]
        p4 = [em.enc(v, i, m) for v, i, m in zip(vs, i4, ms)]
        ok = all(bool(torch.equal(em.dec(p, i, m), torch.round(v - m) + m))
                 for p, i, m, v in zip(p4, i4, ms, vs))
        t_enc = med(lambda: [em.enc(v, i, m) for v, i, m in zip(vs, i4, ms)], iters)
        t_dec = med(lambda: [em.dec(p, i, m) for p, i, m in zip(p4, i4, ms)], iters)
        t_idx = med(lambda: [em.idx(s) for s in ss], iters)
    y_bytes = sum(len(p) for p in p4)
    z_bytes = (n_z * Z_INDEX_BITS + 7) // 8
    return dict(dir=os.path.basename(d), size=S, q=q, symbols=total_sym,
                y_bytes=y_bytes, z_bytes=z_bytes, header=HEADER,
                total_bytes=y_bytes + z_bytes + HEADER,
                bpp=(y_bytes + z_bytes + HEADER) * 8.0 / (S * S),
                y_bpp=y_bytes * 8.0 / (S * S),
                ae_ms=t_enc, ad_ms=t_dec, idx_ms=t_idx, roundtrip_ok=ok)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--iters", type=int, default=10)
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    subs = sorted(d for d in os.listdir(a.root)
                  if os.path.isdir(os.path.join(a.root, d)))
    if not subs:
        print("no per-image subdirs; run dump_entropy_operands.py --n N first")
        return 1
    em = EM()
    rows = [run_one(os.path.join(a.root, d), em, a.iters) for d in subs]

    print("=== 真实 GLC2 整包大小（含 44 B 固定头）与熵编解码耗时 ===")
    print("%-8s %8s %8s %8s %8s %10s %9s %9s %6s"
          % ("img", "y(B)", "z(B)", "头(B)", "整包(B)", "bpp", "AE(ms)", "AD(ms)", "自检"))
    for r in rows:
        print("%-8s %8d %8d %8d %8d %10.5f %9.2f %9.2f %6s"
              % (r["dir"], r["y_bytes"], r["z_bytes"], r["header"], r["total_bytes"],
                 r["bpp"], r["ae_ms"], r["ad_ms"], "OK" if r["roundtrip_ok"] else "FAIL"))

    n = len(rows)
    m = lambda k: sum(r[k] for r in rows) / n
    print("\n均值（%d 张 %dx%d, q=%d）:" % (n, rows[0]["size"], rows[0]["size"], rows[0]["q"]))
    print("  y 负载 %.1f B ｜ z %.1f B ｜ 头 %.1f B ｜ 整包 %.1f B"
          % (m("y_bytes"), m("z_bytes"), m("header"), m("total_bytes")))
    print("  **整包码率 %.5f bpp**（其中 y 占 %.5f）" % (m("bpp"), m("y_bpp")))
    print("  头占比 %.1f%% ｜ z 占比 %.1f%% ｜ y 占比 %.1f%%"
          % (100 * m("header") / m("total_bytes"), 100 * m("z_bytes") / m("total_bytes"),
             100 * m("y_bytes") / m("total_bytes")))
    print("  AE %.2f ms ｜ AD %.2f ms ｜ build_indexes %.2f ms" % (m("ae_ms"), m("ad_ms"), m("idx_ms")))
    print("  roundtrip 全部通过: %s" % all(r["roundtrip_ok"] for r in rows))

    if a.json:
        json.dump(dict(rows=rows, mean=dict(bpp=m("bpp"), y_bpp=m("y_bpp"),
                                            total_bytes=m("total_bytes"),
                                            ae_ms=m("ae_ms"), ad_ms=m("ad_ms"))),
                  open(a.json, "w"), indent=2)
        print("  -> " + a.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
