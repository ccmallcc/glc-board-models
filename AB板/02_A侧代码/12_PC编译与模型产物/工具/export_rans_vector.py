#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Export an rANS test vector from compressai for bit-exact C++ cross-check.

Writes a plain-text vector containing everything `encode_with_indexes` needs:

    PRECISION / NUM_CDFS
    CDF_LENGTH[i]        true length of CDF row i  (cdfs_sizes)
    OFFSET[i]            symbol offset for row i
    CDF i  v0 v1 ...     the (padded) quantized CDF row
    NUM_SYMBOLS / SYMBOLS / INDEXES
    EXPECTED_HEX         the exact bytes compressai produced

The C++ port (rans_port.cpp) reads this file, re-encodes, and must reproduce
EXPECTED_HEX byte for byte.

Usage:
  python3 export_rans_vector.py --ops /mnt/e/.../entropy_ops --phase 0 \
      --out /mnt/e/.../rans/vector_phase0.txt
"""
import argparse
import math
import os
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

    def decompress(self, payload, indexes, means):
        return self.model.decompress([payload], indexes, means=means)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ops", required=True)
    ap.add_argument("--phase", type=int, default=0)
    ap.add_argument("--tile", type=int, default=-1,
                    help=">=0: use only the first N symbols (smaller vector)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    C, L = 256, 16
    sh = (1, C, L, L // 4)
    sym = np.load(os.path.join(a.ops, "phase%d_symbols.npy" % a.phase))
    scl = np.load(os.path.join(a.ops, "phase%d_scales.npy" % a.phase))
    mns = np.load(os.path.join(a.ops, "phase%d_means.npy" % a.phase))

    values = torch.from_numpy(sym).reshape(sh)
    scales = torch.from_numpy(scl).reshape(sh)
    means = torch.from_numpy(mns).reshape(sh)
    if a.tile > 0:                      # truncate the flat symbol stream
        values = values.reshape(-1)[:a.tile].reshape(1, 1, 1, -1)
        scales = scales.reshape(-1)[:a.tile].reshape(1, 1, 1, -1)
        means = means.reshape(-1)[:a.tile].reshape(1, 1, 1, -1)

    em = ELICGaussianConditional(torch.device("cpu"))
    with torch.no_grad():
        indexes = em.build_indexes(scales)
        payloads = em.compress(values, indexes, means)
        payload = payloads[0]
        symbols = em.model.quantize(values, "symbols", means)

        cdf = em.model._quantized_cdf            # (num_cdfs, padded_len) int32
        clen = em.model._cdf_length.reshape(-1)  # (num_cdfs,)
        off = em.model._offset.reshape(-1)       # (num_cdfs,)

        # bit-exact self-check on the Python side
        dec = em.decompress(payload, indexes, means)
        assert torch.equal(dec, torch.round(values - means) + means), "roundtrip failed"

    sym_list = symbols.reshape(-1).int().tolist()
    idx_list = indexes.reshape(-1).int().tolist()
    print("符号数 %d ｜ 用到的 CDF 行数 %d（表共 %d 行，填充长度 %d）"
          % (len(sym_list), len(set(idx_list)), cdf.shape[0], cdf.shape[1]))
    print("compressai 输出 %d 字节" % len(payload))
    print("indexes 取值范围 [%d, %d]" % (min(idx_list), max(idx_list)))

    with open(a.out, "w", encoding="utf-8") as f:
        w = f.write
        w("# rANS test vector exported from compressai %s\n"
          % __import__("compressai").__version__)
        w("PRECISION 16\n")
        w("NUM_CDFS %d\n" % cdf.shape[0])
        w("PADDED_LEN %d\n" % cdf.shape[1])
        w("CDF_LENGTH " + " ".join(str(int(v)) for v in clen.tolist()) + "\n")
        w("OFFSET " + " ".join(str(int(v)) for v in off.tolist()) + "\n")
        for i in range(cdf.shape[0]):
            row = cdf[i].tolist()
            w("CDF %d " % i + " ".join(str(int(v)) for v in row) + "\n")
        w("NUM_SYMBOLS %d\n" % len(sym_list))
        w("SYMBOLS " + " ".join(str(v) for v in sym_list) + "\n")
        w("INDEXES " + " ".join(str(v) for v in idx_list) + "\n")
        w("EXPECTED_LEN %d\n" % len(payload))
        w("EXPECTED_HEX " + payload.hex() + "\n")
    print("-> %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
