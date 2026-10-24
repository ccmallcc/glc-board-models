#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Board-path STRESS vector: exercise all 64 CDF rows through the *compact*
table lookup, including escapes and multi-group bypass.

Why: the four real phase vectors only ever touch rows 0..19 (index range
[0,19]) because GLC's real scales are small.  A bug in GLC_ROW_START for high
row indices (row_start goes up to sum(cdf_length)-len = 27256-3133 = 24123)
would therefore go completely unnoticed by the real-data test.

Coverage targets per row k:
  * the two support edges  (-pmf_center, +pmf_center)
  * interior points        (-1, 0, +1)
  * single-step escapes    (-(pmf_center+1), +(pmf_center+1))
  * moderate escapes       (+-1000)
  * deep escapes           (+-1e6, +-1e7)  -> multi-group bypass
Kept strictly inside compressai's safe domain (n_bypass <= 7, i.e.
raw_val < 2^28), because beyond that compressai itself is UB.

Usage:
  python3 tools/export_rans_board_stress.py --out rans/boardvec_stress.txt
"""
import argparse
import math
import struct
import sys

import numpy as np
import torch
from compressai.entropy_models import GaussianConditional

SCALE_MIN, SCALE_MAX, SCALE_LEVELS = 0.11, 256.0, 64


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--n_random", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=20260912)
    a = ap.parse_args()

    scale_table = torch.exp(
        torch.linspace(math.log(SCALE_MIN), math.log(SCALE_MAX), SCALE_LEVELS))
    model = GaussianConditional(None)
    model.update_scale_table(scale_table, force=True)

    pmf_center = (-model._offset.reshape(-1)).to(torch.int64)   # 1 .. 1565

    scales_l, symbols_l = [], []

    def add(s, v):
        scales_l.append(float(s))
        symbols_l.append(int(v))

    # ---- 1. structured sweep: every CDF row, edges + interior + escapes -----
    for k in range(SCALE_LEVELS):
        s = float(scale_table[k])
        c = int(pmf_center[k])
        for v in (-c, -1, 0, 1, c,               # interior / support edges
                  -(c + 1), (c + 1),             # single-step escape
                  -1000, 1000,                   # moderate escape
                  -1000000, 1000000,             # deep escape  (n_bypass ~ 5)
                  -10000000, 10000000):          # deeper escape(n_bypass ~ 6)
            add(s, v)

    # ---- 2. in-between scales (midpoints) to catch boundary mistakes --------
    st = scale_table.tolist()
    for k in range(SCALE_LEVELS - 1):
        s = (st[k] + st[k + 1]) * 0.5
        add(s, 0); add(s, 1); add(s, -1); add(s, 1000); add(s, -1000)

    # ---- 3. out-of-table scales --------------------------------------------
    for s in (0.0, 1e-30, 0.05, 0.1099, 255.99, 256.0, 256.1, 1e4, 1e30):
        add(s, 0); add(s, 1); add(s, -1)

    # ---- 4. random: scales log-uniform over the real range, residuals normal -
    rng = np.random.default_rng(a.seed)
    rs = np.exp(rng.uniform(math.log(0.11), math.log(30.0), a.n_random))
    rv = np.clip(np.round(rng.normal(0, 1.2, a.n_random)), -6, 6)
    for s, v in zip(rs.tolist(), rv.tolist()):
        add(s, int(v))

    scales = torch.tensor(scales_l, dtype=torch.float32).reshape(1, 1, 1, -1)
    symbols = torch.tensor(symbols_l, dtype=torch.float32).reshape(1, 1, 1, -1)

    # means = 0 so that quantize(values, "symbols", 0) == round(values) == symbols
    means = torch.zeros_like(scales)

    with torch.no_grad():
        indexes = model.build_indexes(scales)
        payload = model.compress(symbols, indexes, means=means)[0]
        got = model.quantize(symbols, "symbols", means)
        assert torch.equal(got.reshape(-1).to(torch.int64),
                           torch.tensor(symbols_l, dtype=torch.int64)), \
            "means=0 round-trip failed"

        # cross-check: a plain rANS decode must give the symbols back
        dec = model.decompress([payload], indexes, means=means)
        assert torch.equal(dec, symbols), "compressai self-roundtrip failed"

    idx = indexes.reshape(-1).to(torch.int64).numpy()
    sc = scales.reshape(-1).to(torch.float32).numpy()
    sc_bits = np.frombuffer(sc.tobytes(), dtype=np.uint32)
    sym = np.array(symbols_l, dtype=np.int64)

    # how many distinct rows, and what is the largest row_start we exercise?
    rows = sorted(set(idx.tolist()))
    clen = model._cdf_length.reshape(-1).to(torch.int64).numpy()
    row_start = np.concatenate([[0], np.cumsum(clen)[:-1]])
    print("符号数 %d ｜ 用到的 CDF 行 %d / 64 ｜ index 范围 [%d, %d]"
          % (len(sym), len(rows), int(idx.min()), int(idx.max())))
    print("最大 row_start = %d（紧凑表共 %d 项）-> %s"
          % (int(row_start.max()), int(row_start[-1] + clen[-1]),
             "覆盖了紧凑表的高位区域 ✅" if row_start.max() > 20000 else "高位未覆盖 ⚠️"))
    print("compressai 输出 %d 字节" % len(payload))
    cov = np.zeros(64, dtype=bool); cov[idx] = True
    print("64 行覆盖: %d/64 %s" % (int(cov.sum()), "✅" if cov.all() else "❌"))

    with open(a.out, "w", encoding="utf-8") as f:
        w = f.write
        w("# board-path rANS STRESS vector (all 64 CDF rows, escapes, bypass)\n")
        w("PRECISION 16\n")
        w("NUM_SYMBOLS %d\n" % len(sym))
        w("SYMBOLS " + " ".join(str(int(v)) for v in sym.tolist()) + "\n")
        w("SCALES " + " ".join("%08x" % int(v) for v in sc_bits.tolist()) + "\n")
        w("# 以下仅供人工核对，板端编码器不使用：\n")
        w("REF_INDEXES " + " ".join(str(int(v)) for v in idx.tolist()) + "\n")
        w("EXPECTED_LEN %d\n" % len(payload))
        w("EXPECTED_HEX " + payload.hex() + "\n")
    print("-> %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
