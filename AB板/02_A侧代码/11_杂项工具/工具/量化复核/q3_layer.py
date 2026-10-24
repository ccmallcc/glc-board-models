# -*- coding: utf-8 -*-
r"""Layer-wise int8-vs-tf32 probe for s4.

1. aligns the HardOp sequences of two *_ZG.json models with difflib on
   (kind, output shape)
2. picks ~N aligned ops spread over the depth
3. runs icraft-run (Host backend) on each model with --dump_ftmp <v_id list>
4. reports, per picked op: SNR between the two dumps + tensor stats

Usage: python q3_layer.py <int8_ZG.json> <tf32_ZG.json> <input.ftmp> <outdir> [npick]
"""
import csv
import difflib
import glob
import math
import os
import subprocess
import sys

import numpy as np

BIN = r"E:\fudanwei\Icraft-3.36.1\bin"


def read_csv(p):
    rows = []
    for r in csv.DictReader(open(p, encoding="utf-8")):
        rows.append(r)
    return rows


def key(r):
    return "%s|%s" % (r["kind"], r["shape"])


def align(ra, rb):
    a = [key(r) for r in ra]
    b = [key(r) for r in rb]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    pairs = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                pairs.append((i1 + k, j1 + k))
    return pairs


def psnr_snr(x, y):
    mse = float(np.mean((x.astype("f8") - y.astype("f8")) ** 2))
    rng = float(max(x.max(), y.max()) - min(x.min(), y.min()))
    pk = 10 * math.log10(rng * rng / mse) if mse > 0 else 999.0
    sg = 10 * math.log10(float(np.mean(y.astype("f8") ** 2)) / mse) if mse > 0 else 999.0
    return pk, sg, math.sqrt(mse)


def main():
    j8, j32, inp, out = sys.argv[1:5]
    npick = int(sys.argv[5]) if len(sys.argv) > 5 else 16
    os.makedirs(out, exist_ok=True)
    ca, cb = os.path.join(out, "ops_i8.csv"), os.path.join(out, "ops_tf32.csv")
    for j, c in ((j8, ca), (j32, cb)):
        r = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "ops_probe.py"),
                            j, "--csv", c, "--top", "0"], capture_output=True)
        if r.returncode:
            print(r.stdout.decode("utf-8", "replace"))
            return 1
    ra, rb = read_csv(ca), read_csv(cb)
    pairs = align(ra, rb)
    print("aligned ops: %d / (int8 %d, tf32 %d)" % (len(pairs), len(ra), len(rb)))

    # pick ops that carry real data, spread over the depth
    good = []
    for i, j in pairs:
        A, B = ra[i], rb[j]
        n = int(A["numel"])
        if n < 4096 or n > 1 << 22:
            continue
        if A["storage"] in ("", "@fp(32)") and B["storage"] in ("", "@fp(32)"):
            pass
        good.append((i, j, A, B))
    print("usable aligned ops: %d" % len(good))
    step = max(1, len(good) // npick)
    pick = good[::step][:npick]
    ids8 = ",".join(p[2]["v_id"] for p in pick)
    ids32 = ",".join(p[3]["v_id"] for p in pick)

    dumps = []
    for tag, j, ids in (("i8", j8, ids8), ("tf32", j32, ids32)):
        ld = os.path.join(out, "run_" + tag)
        cmd = [os.path.join(BIN, "icraft-run.exe"), "--json", j,
               "--raw", j.replace("_ZG.json", "_ZG.raw"), "--input", inp,
               "--backends", "Host", "--log_path", ld,
               "--dump_format", "SFB", "--dump_ftmp", ids]
        print("run %s ..." % tag, flush=True)
        r = subprocess.run(cmd, capture_output=True)
        hits = glob.glob(os.path.join(ld, "**", "ftmpSFB"), recursive=True)
        dumps.append(hits[0] if hits else os.path.join(ld, "ftmpSFB"))
        print("   rc=%d  dump_dir=%s" % (r.returncode, dumps[-1]), flush=True)

    print("%-6s %-22s %-14s %-10s %-9s %-9s %s"
          % ("idx8", "kind", "shape", "numel", "PSNR", "SNR", "scale"))
    for (i, j, A, B) in pick:
        fa = os.path.join(dumps[0], A["v_id"] + ".ftmp")
        fb = os.path.join(dumps[1], B["v_id"] + ".ftmp")
        if not (os.path.exists(fa) and os.path.exists(fb)):
            print("%-6s %-22s %-14s %-10s MISSING" % (i, A["kind"], A["shape"], A["numel"]))
            continue
        x = np.fromfile(fa, dtype="<f4")
        y = np.fromfile(fb, dtype="<f4")
        if x.size != y.size:
            print("%-6s %-22s %-14s %-10s SIZE %d vs %d" % (i, A["kind"], A["shape"], A["numel"], x.size, y.size))
            continue
        pk, sg, rm = psnr_snr(x, y)
        print("%-6d %-22s %-14s %-10s %-9.2f %-9.2f %s %s"
              % (i, A["kind"], A["shape"], A["numel"], pk, sg, A["skind"], A["scale"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
