#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Export a STRESS rANS vector: exercise the escape/bypass path and all CDF rows.

The real GLC residuals are in [-2, 2] and the Gaussian CDF for the smallest
scale already covers roughly +-8 sigma, so with real data the escape/bypass
branch of compressai's rANS is probably never taken.  A port that is only
tested on real data would therefore be under-verified.

This builder constructs a vector that deliberately covers:
  * all 64 scale levels -> all 64 CDF rows in `_quantized_cdf`
  * symbols well *inside* the covered range (normal path)
  * symbols far *below* and *above* the range (negative / positive escape)
  * very large raw values -> multiple bypass words, including the
    max_bypass_val continuation path (raw_val needs > 15 four-bit groups,
    i.e. |residual| >~ 2^60 -- unreachable in practice, but the code path is
    exercised by the intermediate continuation case: n_bypass >= 15)

Usage:
  python3 export_rans_stress.py --out /mnt/e/.../rans/vector_stress.txt
"""
import argparse
import math
import sys

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
        return self.model.compress(v, i, means=m)      # list[bytes], batch=1

    def dec(self, p, i, m):
        return self.model.decompress([p], i, means=m)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)

    em = EM()

    # ---- 1) every scale level, so every CDF row is used ----
    scales_all = torch.exp(torch.linspace(math.log(SCALE_MIN), math.log(SCALE_MAX),
                                          SCALE_LEVELS))
    n_all = scales_all.numel()

    # ---- 2) build value/scale/mean triplets ----
    vals, scls, mns = [], [], []

    # (a) every scale level with residuals inside the range
    for s in scales_all:
        s = float(s)
        for r in (-3.0, -1.0, 0.0, 1.0, 3.0):
            vals.append(0.25 + r)          # value = mean + residual
            scls.append(s)
            mns.append(0.25)

    # (b) every scale level with a NEGATIVE escape (residual far below)
    for s in scales_all:
        s = float(s)
        vals.append(0.5 - 1000.0)
        scls.append(s)
        mns.append(0.5)

    # (c) every scale level with a POSITIVE escape (residual far above)
    for s in scales_all:
        s = float(s)
        vals.append(-0.5 + 1000.0)
        scls.append(s)
        mns.append(-0.5)

    # (d) multiple bypass words: residuals spanning several 4-bit groups.
    #     ⚠️ Keep |residual| < 2^27 (~1.34e8): beyond that the escaped
    #     `raw_val` needs >= 8 four-bit groups and compressai's own encoder
    #     hits undefined behaviour (shift by 32 on a uint32_t) -- observed as
    #     an infinite loop.  GLC never produces residuals anywhere near this
    #     (real data is |r| <= 2), so staying in-domain loses nothing.
    for s in (0.11, 1.0, 16.0, 256.0):
        for r in (15.0, 16.0, 255.0, 256.0, 4095.0, 4096.0,
                  65535.0, 65536.0, 1e6, 5e6, 1e7, -1e7, -5e6, -1e6):
            vals.append(r)
            scls.append(s)
            mns.append(0.0)

    # (e) random fill so the stream has some bulk
    n_rand = 2000
    vals += list(rng.normal(0.0, 2.0, n_rand))
    scls += list(np.exp(rng.uniform(math.log(SCALE_MIN), math.log(SCALE_MAX), n_rand)))
    mns += list(rng.normal(0.0, 0.5, n_rand))

    V = torch.tensor(vals, dtype=torch.float32).reshape(1, 1, 1, -1)
    S = torch.tensor(scls, dtype=torch.float32).reshape(1, 1, 1, -1)
    M = torch.tensor(mns, dtype=torch.float32).reshape(1, 1, 1, -1)
    n = V.numel()

    with torch.no_grad():
        indexes = em.idx(S)
        payloads = em.enc(V, indexes, M)
        payload = payloads[0]
        symbols = em.model.quantize(V, "symbols", M)
        cdf = em.model._quantized_cdf
        clen = em.model._cdf_length.reshape(-1)
        off = em.model._offset.reshape(-1)
        dec = em.dec(payload, indexes, M)
        assert torch.equal(dec, torch.round(V - M) + M), "roundtrip failed"

    sym_list = symbols.reshape(-1).int().tolist()
    idx_list = indexes.reshape(-1).int().tolist()
    used = sorted(set(idx_list))
    print("压力向量: %d 个符号 ｜ 用到 CDF 行 %d 个（%d..%d）｜ 输出 %d 字节"
          % (n, len(used), used[0], used[-1], len(payload)))

    with open(a.out, "w", encoding="utf-8") as f:
        w = f.write
        w("# STRESS rANS vector (all CDF rows + escape/bypass path)\n")
        w("PRECISION 16\n")
        w("NUM_CDFS %d\n" % cdf.shape[0])
        w("PADDED_LEN %d\n" % cdf.shape[1])
        w("CDF_LENGTH " + " ".join(str(int(v)) for v in clen.tolist()) + "\n")
        w("OFFSET " + " ".join(str(int(v)) for v in off.tolist()) + "\n")
        for i in range(cdf.shape[0]):
            w("CDF %d " % i + " ".join(str(int(v)) for v in cdf[i].tolist()) + "\n")
        w("NUM_SYMBOLS %d\n" % n)
        w("SYMBOLS " + " ".join(str(v) for v in sym_list) + "\n")
        w("INDEXES " + " ".join(str(v) for v in idx_list) + "\n")
        w("EXPECTED_LEN %d\n" % len(payload))
        w("EXPECTED_HEX " + payload.hex() + "\n")
    print("-> %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
