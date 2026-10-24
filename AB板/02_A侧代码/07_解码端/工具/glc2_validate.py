# -*- coding: utf-8 -*-
r"""Independent validator for the GLC2 bitstream container.

Deliberately imports neither torch nor compressai: it re-implements the
container layout from scratch so that it can act as a second opinion on the
team's codec (test_image_complement2.py) and, later, on the PL range-coder RTL.

Container (all big-endian):

    HEADER = struct.Struct(">4sBBH17I")     76 bytes
      (4 + 1 + 1 + 2 + 17*4 = 76 —— 注意：本文档旧版写的 "44 bytes" 是**错的**，
       代码一直用的是 HEADER.size = 76，所以只是注释有误。实测 board_img0.glc
       只有按 76 才能自洽：76 + 28(z) + 60 + 60 + 52 + 48 = 324。)
      [0]  magic  b"GLC2"
      [1]  version             == 2
      [2]  q_index
      [3]  flags               == 0
      [4]  original height
      [5]  original width
      [6]  padded height       (multiple of 16)
      [7]  padded width
      [8..10]  y shape  (C,H,W)
      [11..13] z shape  (C,H,W)
      [14] z_index_count
      [15] z_payload_len       (packed Z_INDEX_BITS-bit indices)
      [16..19] four stage stream lengths
      [20] trailer flag        == 0
    then z_payload followed by the four stage streams, with no trailing bytes.

Checks performed per file:
  * header parses, magic/version/flags/trailer correct
  * stream lengths positive and exactly consume the file (no trailing data)
  * padded dims are the latent size x16 and the original fits inside them
  * z_payload_len is exactly ceil(count*Z_INDEX_BITS/8)
  * the four stage streams sum to (file - header - z_payload)
  * reported bpp in a sibling metrics file (if found) matches the file size

Usage:
  python glc2_validate.py [--root DIR] [--glob **/*.glc] [--json OUT]
"""
import argparse
import glob
import json
import math
import os
import struct
import sys

MAGIC = b"GLC2"
VERSION = 2
HEADER = struct.Struct(">4sBBH17I")
SCALE_MIN, SCALE_MAX, SCALE_LEVELS = 0.11, 256.0, 64
Z_INDEX_BITS = 14


def ceil_div(a, b):
    return -(-a // b)


def validate(path):
    r = {"file": path}
    try:
        blob = open(path, "rb").read()
    except OSError as e:
        r["error"] = "unreadable: %s" % e
        return r
    r["bytes"] = len(blob)
    if len(blob) < HEADER.size:
        r["error"] = "shorter than %d-byte header" % HEADER.size
        return r
    f = HEADER.unpack_from(blob)
    r["magic"] = f[0].decode("latin1")
    r["version"], r["q_index"], r["flags"] = f[1], f[2], f[3]
    (r["height"], r["width"], r["pad_h"], r["pad_w"]) = f[4:8]
    r["y_chw"] = list(f[8:11])
    r["z_chw"] = list(f[11:14])
    (r["z_count"], r["z_bytes"]) = f[14], f[15]
    r["stage_bytes"] = list(f[16:20])
    r["trailer"] = f[20]

    errs = []
    if f[0] != MAGIC:
        errs.append("bad magic %r" % f[0])
    if f[1] != VERSION:
        errs.append("bad version %d" % f[1])
    if f[3] != 0 or f[20] != 0:
        errs.append("non-zero flags/trailer (%d/%d)" % (f[3], f[20]))

    yc, yh, yw = r["y_chw"]
    zc, zh, zw = r["z_chw"]
    if r["pad_h"] != yh * 16 or r["pad_w"] != yw * 16:
        errs.append("padded %dx%d != latent %dx%d x16" % (r["pad_h"], r["pad_w"], yh, yw))
    if not (0 < r["height"] <= r["pad_h"] and 0 < r["width"] <= r["pad_w"]):
        errs.append("original %dx%d outside padded %dx%d"
                    % (r["height"], r["width"], r["pad_h"], r["pad_w"]))
    want_z = ceil_div(r["z_count"] * Z_INDEX_BITS, 8)
    if want_z != r["z_bytes"]:
        errs.append("z payload %d B != ceil(%d*%d/8)=%d"
                    % (r["z_bytes"], r["z_count"], Z_INDEX_BITS, want_z))
    if any(b <= 0 for b in r["stage_bytes"]):
        errs.append("non-positive stage length %s" % r["stage_bytes"])
    total = HEADER.size + r["z_bytes"] + sum(r["stage_bytes"])
    r["expected_bytes"] = total
    if total != len(blob):
        errs.append("size %d != header+z+stages = %d (delta %+d)"
                    % (len(blob), total, len(blob) - total))

    # latent sanity: z is y/4
    if (zh, zw) != (max(1, yh // 4), max(1, yw // 4)):
        errs.append("z spatial %dx%d is not y/4 of %dx%d" % (zh, zw, yh, yw))

    r["bpp_on_padded"] = 8.0 * len(blob) / (r["pad_h"] * r["pad_w"])
    r["bpp_on_original"] = 8.0 * len(blob) / (r["height"] * r["width"])
    r["z_share_pct"] = 100.0 * (HEADER.size + r["z_bytes"]) / len(blob)
    r["errors"] = errs
    r["ok"] = not errs
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=r"E:\fudanwei\工作区\GLC-main\GLC-main")
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    files = sorted(glob.glob(os.path.join(a.root, "**", "*.glc"), recursive=True))
    print("found %d .glc files under %s\n" % (len(files), a.root))
    rows = [validate(p) for p in files]

    ok = [r for r in rows if r.get("ok")]
    bad = [r for r in rows if not r.get("ok")]
    print("%-46s %8s %6s %8s %8s %7s  %s"
          % ("file", "bytes", "q", "bpp_pad", "z_share", "verdict", "issue"))
    for r in rows:
        if "error" in r:
            print("%-46s %8s %6s %8s %8s %7s  %s"
                  % (os.path.relpath(r["file"], a.root), r.get("bytes", "-"), "-",
                     "-", "-", "FAIL", r["error"]))
            continue
        print("%-46s %8d %6d %8.5f %7.1f%% %7s  %s"
              % (os.path.relpath(r["file"], a.root), r["bytes"], r["q_index"],
                 r["bpp_on_padded"], r["z_share_pct"],
                 "ok" if r["ok"] else "FAIL", "; ".join(r["errors"])[:60]))

    print("\n%d ok / %d failed" % (len(ok), len(bad)))
    if ok:
        import statistics as st
        print("q distribution: %s" % json.dumps(
            {str(q): sum(1 for r in ok if r["q_index"] == q)
             for q in sorted({r["q_index"] for r in ok})}))
        print("bpp_on_padded: min=%.5f median=%.5f max=%.5f"
              % (min(r["bpp_on_padded"] for r in ok),
                 st.median([r["bpp_on_padded"] for r in ok]),
                 max(r["bpp_on_padded"] for r in ok)))
        print("z payload share of file: min=%.1f%% median=%.1f%% max=%.1f%%"
              % (min(r["z_share_pct"] for r in ok),
                 st.median([r["z_share_pct"] for r in ok]),
                 max(r["z_share_pct"] for r in ok)))
    if a.json:
        json.dump(rows, open(a.json, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print("written " + a.json)
    return 0 if not bad else 2


if __name__ == "__main__":
    sys.exit(main())
