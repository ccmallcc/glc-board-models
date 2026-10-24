#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""V2: export the rANS CDF tables as a *compact* board-loadable constant file,
plus a scale->index verification vector.

Why this exists
---------------
compressai stores the 64 CDF rows padded to a common length (64 x 3133 int32 =
6.12 Mb).  On the PL that would eat 69% of the 9.3 Mb BRAM, but **86.4% of the
padded entries are unused** (the true total is sum(cdf_length) = 27256 entries).
This script emits the compact form:

    SCALE_TABLE[64]   float32   the 64-level scale table (NOT padded)
    SCALE_BOUND       float32   the clamp constant actually used by LowerBound
    CDF_LENGTH[64]    uint32    true length of each CDF row (incl. the 2 sentinels)
    CDF_OFFSET[64]    int32     symbol offset for each row
    ROW_START[64]     uint32    prefix sum of CDF_LENGTH -> start of each row
    CDF_FLAT[27256]   uint32    the compacted CDF rows, concatenated

It also writes a scale->index vector so the C++ side can prove its
`build_indexes` port is bit-exact.

The scale->index rule (compressai GaussianConditional.build_indexes):

    scales = max(scales, scale_bound)                      # float32, bound = 0.11
    index  = 63
    for s in scale_table[:-1]:        # 63 entries, ascending
        index -= (scales <= s)

i.e. `index = 63 - |{ i < 63 : scale <= table[i] }|`, which is
`searchsorted(table, scale, side='left')`.

Outputs (default --outdir rans):
    glc_cdf_table.h     C header (board include)
    glc_cdf_table.bin   binary blob, documented layout
    vector_indexes.txt  scale->index verification vector (hex float32 bits)
    cdf_table_meta.json dimensions + checksums

Usage:
  python3 tools/export_cdf_table.py --outdir /mnt/e/fudanwei/工作区/rans \
      --ops /mnt/e/fudanwei/工作区/entropy_ops
"""
import argparse
import hashlib
import json
import math
import os
import struct
import sys

import numpy as np
import torch
from compressai.entropy_models import GaussianConditional

SCALE_MIN, SCALE_MAX, SCALE_LEVELS = 0.11, 256.0, 64
PRECISION = 16


def f32_bits(v):
    """float32 bit pattern of a python float, as uint32."""
    return struct.unpack("<I", struct.pack("<f", float(v)))[0]


def build_model():
    """Exactly the team's wrapper (test_image_complement2.py)."""
    scale_table = torch.exp(
        torch.linspace(math.log(SCALE_MIN), math.log(SCALE_MAX), SCALE_LEVELS))
    model = GaussianConditional(None)
    model.update_scale_table(scale_table, force=True)
    return model


def build_indexes_py(model, scales):
    """Reference implementation, verbatim from compressai."""
    return model.build_indexes(scales)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--ops", default=None,
                    help="entropy_ops dir; if given, real scales are used as vectors")
    ap.add_argument("--n_fuzz", type=int, default=200000)
    a = ap.parse_args()

    os.makedirs(a.outdir, exist_ok=True)
    model = build_model()

    scale_table = model.scale_table.reshape(-1)          # float32, 64
    bound = float(model.scale_bound.reshape(-1)[0])      # float32 0.11 -> python float
    cdf = model._quantized_cdf                           # (64, 3133) int32
    clen = model._cdf_length.reshape(-1).to(torch.int64)
    off = model._offset.reshape(-1).to(torch.int64)

    n_rows, padded = cdf.shape
    assert n_rows == SCALE_LEVELS == 64, n_rows

    # --- prove compaction is lossless: padded tail must be all zero ------------
    tail_used = int(clen.max().item())
    tail = cdf[:, tail_used:]
    assert int(tail.abs().sum().item()) == 0, "padded tail is NOT zero -> cannot compact"
    print("[ok] 填充尾巴全为 0（%d..%d 列），紧凑化无损" % (tail_used, padded - 1))

    clen_l = [int(v) for v in clen.tolist()]
    off_l = [int(v) for v in off.tolist()]
    row_start = []
    acc = 0
    for n in clen_l:
        row_start.append(acc)
        acc += n
    total = acc
    print("[ok] 紧凑条目数 = %d（填充表 %d x %d = %d，浪费 %.2f%%）"
          % (total, n_rows, padded, n_rows * padded,
             100.0 * (n_rows * padded - total) / (n_rows * padded)))

    # --- build the flat compact table ----------------------------------------
    flat = np.zeros(total, dtype=np.uint32)
    for i in range(n_rows):
        row = cdf[i, :clen_l[i]].to(torch.int64).numpy()
        assert row[0] == 0, "CDF row %d does not start at 0" % i
        assert row[-1] == (1 << PRECISION), \
            "CDF row %d does not end at 2^%d (=%d), got %d" % (i, PRECISION, 1 << PRECISION, row[-1])
        assert (np.diff(row) >= 0).all(), "CDF row %d is not monotone" % i
        flat[row_start[i]:row_start[i] + clen_l[i]] = row.astype(np.uint32)
    print("[ok] 每行首=0、末=%d、单调不减，全部 64 行通过" % (1 << PRECISION))

    # --- scale table + bound, as exact bit patterns ---------------------------
    st_bits = [f32_bits(v) for v in scale_table.tolist()]
    bound_bits = f32_bits(bound)
    print("[ok] SCALE_BOUND  = %.10g (float32 bits 0x%08X)" % (bound, bound_bits))
    print("[ok] scale_table[0] = %.10g (float32 bits 0x%08X)  %s"
          % (scale_table[0].item(), st_bits[0],
             "== bound" if st_bits[0] == bound_bits else "!= bound (差 1 ulp 级，必须分别存)"))

    # --- verification vectors: scale (float32 bits) -> expected index ---------
    cases = []   # (bits, index)

    def add(scales_np):
        t = torch.from_numpy(scales_np.astype(np.float32))
        idx = build_indexes_py(model, t).reshape(-1).to(torch.int64).numpy()
        b = np.frombuffer(t.numpy().astype(np.float32).tobytes(), dtype=np.uint32)
        for bb, ii in zip(b.tolist(), idx.tolist()):
            cases.append((bb, ii))

    # (1) every table entry exactly, plus +-1 ulp around it  -> boundary coverage
    tb = np.array(st_bits, dtype=np.uint32)
    add(np.frombuffer(tb.tobytes(), dtype=np.float32).copy())
    add(np.frombuffer((tb + 1).tobytes(), dtype=np.float32).copy())
    add(np.frombuffer((tb - 1).tobytes(), dtype=np.float32).copy())
    # (2) midpoints between consecutive entries
    st = np.array(scale_table.tolist(), dtype=np.float32)
    add(((st[:-1] + st[1:]) * np.float32(0.5)).astype(np.float32))
    # (3) below / above the table
    add(np.array([0.0, 1e-30, 0.05, 0.1099, 0.11], dtype=np.float32))
    add(np.array([255.9, 256.0, 256.1, 300.0, 1e4, 1e30], dtype=np.float32))
    # (4) real GLC scales from the 4 phases
    n_real = 0
    if a.ops and os.path.isdir(a.ops):
        for ph in range(4):
            p = os.path.join(a.ops, "img0", "phase%d_scales.npy" % ph)
            if os.path.exists(p):
                add(np.load(p).reshape(-1).astype(np.float32))
                n_real += 1
    # (5) uniform fuzz across the whole plausible range
    rng = np.random.default_rng(1234)
    add(rng.uniform(0.0, 300.0, a.n_fuzz).astype(np.float32))
    # (6) log-uniform fuzz (matches the actual distribution shape better)
    add(np.exp(rng.uniform(math.log(1e-3), math.log(1e4), a.n_fuzz)).astype(np.float32))

    # dedupe on the bit pattern, keep first expected index
    seen = {}
    for bb, ii in cases:
        if bb not in seen:
            seen[bb] = ii
    items = sorted(seen.items())
    dist = {}
    for bb, ii in items:
        dist[ii] = dist.get(ii, 0) + 1
    print("[ok] 索引向量 %d 条（去重后）；覆盖 index 值 %d / 64 个"
          % (len(items), len(dist)))
    missing = [k for k in range(SCALE_LEVELS) if k not in dist]
    if missing:
        print("[!!] 未被覆盖的 index: %s" % missing)
    else:
        print("[ok] 全部 64 个 index 值都被覆盖")

    # --- write the C header ---------------------------------------------------
    def carr(name, ctype, fmt, vals, per=12):
        out = ["static const %s %s[%d] = {" % (ctype, name, len(vals))]
        for i in range(0, len(vals), per):
            out.append("  " + ", ".join(fmt % v for v in vals[i:i + per]) + ",")
        out.append("};")
        return "\n".join(out)

    h = []
    h.append("/* glc_cdf_table.h -- GENERATED by tools/export_cdf_table.py, DO NOT EDIT.")
    h.append(" *")
    h.append(" * GLC rANS entropy-coding constants for the board (V2).")
    h.append(" *")
    h.append(" * Layout notes")
    h.append(" * ------------")
    h.append(" *  - CDF rows are stored COMPACTLY (no padding).  Where compressai uses")
    h.append(" *    cdf[k][v] the board uses cdf_flat[row_start[k] + v].")
    h.append(" *  - Padded form would be 64*3133*4 = %d B (%.2f Mb, %.1f%% of the"
             % (n_rows * padded * 4, n_rows * padded * 4 * 8 / 1e6,
                100.0 * n_rows * padded * 4 * 8 / 9.3e6))
    h.append(" *    9.3 Mb PL BRAM); this compact form is %d B (%.2f Mb, %.1f%%)."
             % (total * 4, total * 4 * 8 / 1e6, 100.0 * total * 4 * 8 / 9.3e6))
    h.append(" *  - CDF values are in [0, 2^%d]; the last entry of every row is exactly" % PRECISION)
    h.append(" *    2^%d, so uint32 is the natural storage width (17 significant bits)." % PRECISION)
    h.append(" *  - Symbol mapping (must match compressai's rans_interface.cpp):")
    h.append(" *        value = symbol - CDF_OFFSET[k];")
    h.append(" *        max_value = CDF_LENGTH[k] - 2;")
    h.append(" *        value < 0            -> raw_val = -2*value - 1, value = max_value;")
    h.append(" *        value >= max_value   -> raw_val =  2*(value - max_value), value = max_value;")
    h.append(" *        start = cdf[row_start[k] + value];  range = cdf[row_start[k] + value + 1] - start;")
    h.append(" */")
    h.append("#ifndef GLC_CDF_TABLE_H")
    h.append("#define GLC_CDF_TABLE_H")
    h.append("")
    h.append("#include <stdint.h>")
    h.append("")
    h.append("#define GLC_NUM_CDFS      %d" % SCALE_LEVELS)
    h.append("#define GLC_CDF_PRECISION %d" % PRECISION)
    h.append("#define GLC_CDF_ENTRIES   %d" % total)
    h.append("#define GLC_MAX_CDF_LEN   %d" % max(clen_l))
    h.append("")
    h.append("/* float32 clamp constant used by compressai's LowerBound.")
    h.append(" *")
    h.append(" * Subtlety worth keeping in mind: the model is built as")
    h.append(" *     GaussianConditional(None)                       -> scale_table is empty")
    h.append(" *     update_scale_table(scale_table, force=True)     -> sets scale_table only")
    h.append(" * so scale_bound stays the *default* 0.11 and is never re-derived from")
    h.append(" * scale_table.  In this configuration the two happen to be bit-identical")
    h.append(" * (both 0x3DE147AE, verified), but they are different objects and a future")
    h.append(" * scale table with a different minimum would silently break that.  Keep")
    h.append(" * this constant separate. */")
    bound_f = float(np.frombuffer(struct.pack("<I", bound_bits), dtype=np.float32)[0])
    h.append("static const float GLC_SCALE_BOUND = %.9gf; /* 0x%08X */"
             % (bound_f, bound_bits))
    h.append("")
    h.append("/* the 64-level scale table (float32), bit-exact */")
    st_floats = [float(v) for v in scale_table.tolist()]
    h.append(carr("GLC_SCALE_TABLE", "float", "%.9g", st_floats, per=4))
    h.append("")
    h.append("/* true length of each CDF row, including the two sentinels */")
    h.append(carr("GLC_CDF_LENGTH", "uint32_t", "%d", clen_l))
    h.append("")
    h.append("/* symbol offset for each row (all negative) */")
    h.append(carr("GLC_CDF_OFFSET", "int32_t", "%d", off_l))
    h.append("")
    h.append("/* start of each row inside GLC_CDF_FLAT */")
    h.append(carr("GLC_ROW_START", "uint32_t", "%d", row_start))
    h.append("")
    h.append("/* compacted CDF rows, concatenated (see GLC_ROW_START / GLC_CDF_LENGTH) */")
    h.append(carr("GLC_CDF_FLAT", "uint32_t", "%d", flat.tolist()))
    h.append("")
    h.append("/*")
    h.append(" * scale -> CDF row index, bit-exact port of compressai's")
    h.append(" * GaussianConditional.build_indexes (see the report for the derivation).")
    h.append(" */")
    h.append("static inline int glc_build_index(float scale) {")
    h.append("  int idx = GLC_NUM_CDFS - 1;")
    h.append("  if (!(scale > GLC_SCALE_BOUND)) scale = GLC_SCALE_BOUND; /* max(), NaN-safe like torch */")
    h.append("  for (int i = 0; i < GLC_NUM_CDFS - 1; ++i) {")
    h.append("    if (scale <= GLC_SCALE_TABLE[i]) --idx;")
    h.append("  }")
    h.append("  return idx;")
    h.append("}")
    h.append("")
    h.append("/*")
    h.append(" * Binary-search form (identical results, O(log n)).  Use this on the")
    h.append(" * board if the 64-iteration loop shows up in a profile.")
    h.append(" */")
    h.append("static inline int glc_build_index_fast(float scale) {")
    h.append("  int lo = 0, hi = GLC_NUM_CDFS - 1; /* first i with scale <= table[i] */")
    h.append("  if (!(scale > GLC_SCALE_BOUND)) scale = GLC_SCALE_BOUND;")
    h.append("  while (lo < hi) {")
    h.append("    int mid = (lo + hi) >> 1;")
    h.append("    if (scale <= GLC_SCALE_TABLE[mid]) hi = mid; else lo = mid + 1;")
    h.append("  }")
    h.append("  return lo;")
    h.append("}")
    h.append("")
    h.append("#endif /* GLC_CDF_TABLE_H */")
    h.append("")

    hp = os.path.join(a.outdir, "glc_cdf_table.h")
    with open(hp, "w", encoding="utf-8") as f:
        f.write("\n".join(h))
    print("-> %s (%d B)" % (hp, os.path.getsize(hp)))

    # --- write the binary blob -----------------------------------------------
    bp = os.path.join(a.outdir, "glc_cdf_table.bin")
    with open(bp, "wb") as f:
        f.write(b"GCTB")                                   # magic
        f.write(struct.pack("<HHIII", 1, PRECISION, SCALE_LEVELS, total, max(clen_l)))
        f.write(struct.pack("<I", bound_bits))
        f.write(np.array(st_bits, dtype=np.uint32).tobytes())
        f.write(np.array(clen_l, dtype=np.uint32).tobytes())
        f.write(np.array(off_l, dtype=np.int32).tobytes())
        f.write(np.array(row_start, dtype=np.uint32).tobytes())
        f.write(flat.tobytes())
    print("-> %s (%d B)" % (bp, os.path.getsize(bp)))

    # --- write the scale->index vector ---------------------------------------
    vp = os.path.join(a.outdir, "vector_indexes.txt")
    with open(vp, "w", encoding="utf-8") as f:
        f.write("# scale->index vector for GLC rANS (V2)\n")
        f.write("# generated by tools/export_cdf_table.py from compressai\n")
        f.write("NUM_CASES %d\n" % len(items))
        f.write("# each line: <float32 bits, 8 hex digits> <expected index>\n")
        for bb, ii in items:
            f.write("%08x %d\n" % (bb, ii))
    print("-> %s (%d B)" % (vp, os.path.getsize(vp)))

    meta = {
        "num_cdfs": SCALE_LEVELS, "precision": PRECISION,
        "padded_len": int(padded), "compact_entries": int(total),
        "max_cdf_len": int(max(clen_l)), "min_cdf_len": int(min(clen_l)),
        "padded_bytes": int(n_rows * padded * 4), "compact_bytes": int(total * 4),
        "compact_over_padded": round(total / float(n_rows * padded), 6),
        "brram_padded_pct": round(100.0 * n_rows * padded * 4 * 8 / 9.3e6, 3),
        "bram_compact_pct": round(100.0 * total * 4 * 8 / 9.3e6, 3),
        "scale_bound": bound, "scale_bound_bits": "0x%08X" % bound_bits,
        "scale_table0_bits": "0x%08X" % st_bits[0],
        "scale_bound_equals_table0": st_bits[0] == bound_bits,
        "index_cases": len(items), "index_values_covered": len(dist),
        "real_phases_used": n_real,
        "md5": {
            "glc_cdf_table.h": hashlib.md5(open(hp, "rb").read()).hexdigest(),
            "glc_cdf_table.bin": hashlib.md5(open(bp, "rb").read()).hexdigest(),
            "vector_indexes.txt": hashlib.md5(open(vp, "rb").read()).hexdigest(),
        },
    }
    mp = os.path.join(a.outdir, "cdf_table_meta.json")
    with open(mp, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print("-> %s" % mp)
    print(json.dumps(meta, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
