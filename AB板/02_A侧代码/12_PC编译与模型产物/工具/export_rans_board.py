#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Export a *board-path* rANS vector: symbols + scales (+ expected payload).

Difference from export_rans_vector.py: that one ships precomputed CDF *indexes*
and the padded CDF table, so it only tests the rANS core.  This one ships the
raw per-symbol *scales* (float32 bit patterns) so the C++ side has to do the
whole board pipeline itself:

    scale --glc_build_index--> row k --compact table--> CDF --> rANS --> bytes

That is exactly what runs on the board, with zero compressai dependency at
runtime.  Passing this vector proves V1 (rANS core) and V2 (compact tables +
scale->index) work *together*.

Usage:
  python3 tools/export_rans_board.py --ops entropy_ops/img0 --phase 0 \
      --out rans/boardvec_phase0.txt
"""
import argparse
import math
import os
import struct
import sys

import numpy as np
import torch
from compressai.entropy_models import GaussianConditional

SCALE_MIN, SCALE_MAX, SCALE_LEVELS = 0.11, 256.0, 64


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
        return self.model.compress(values, indexes, means=means)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ops", required=True, help="dir containing phase*_{symbols,scales,means}.npy")
    ap.add_argument("--phase", type=int, default=0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    C, L = 256, 16
    sh = (1, C, L, L // 4)
    val = np.load(os.path.join(a.ops, "phase%d_symbols.npy" % a.phase)).reshape(sh)
    scl = np.load(os.path.join(a.ops, "phase%d_scales.npy" % a.phase)).reshape(sh)
    mns = np.load(os.path.join(a.ops, "phase%d_means.npy" % a.phase)).reshape(sh)

    values = torch.from_numpy(val)
    scales = torch.from_numpy(scl)
    means = torch.from_numpy(mns)

    em = ELICGaussianConditional(torch.device("cpu"))
    with torch.no_grad():
        indexes = em.build_indexes(scales)
        payload = em.compress(values, indexes, means)[0]
        symbols = em.model.quantize(values, "symbols", means)

    sym = symbols.reshape(-1).to(torch.int64).numpy().astype(np.int32)
    sc = scales.reshape(-1).to(torch.float32).numpy()
    sc_bits = np.frombuffer(sc.tobytes(), dtype=np.uint32)
    idx = indexes.reshape(-1).to(torch.int64).numpy()

    print("phase %d: %d 符号, %d 字节, 残差范围 [%d, %d], index 范围 [%d, %d], "
          "用到的 CDF 行 %d"
          % (a.phase, len(sym), len(payload), int(sym.min()), int(sym.max()),
             int(idx.min()), int(idx.max()), len(set(idx.tolist()))))

    with open(a.out, "w", encoding="utf-8") as f:
        w = f.write
        w("# board-path rANS vector (symbols + scales), exported from compressai\n")
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
