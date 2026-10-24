# -*- coding: utf-8 -*-
r"""Trace HostBackend numerics layer-by-layer for a quantized network.

Runs icraft-run --backends Host with an explicit --dump_ftmp list (runtime
v_ids taken from a previous --log_io run), then censuses every dumped tensor.

Usage:
  python hb_trace_dump.py --qjson <q.json> --raw <q.raw> --input <in.ftmp>
                          --tag <name> --vids 0,4,16,36,48,1295,1342,1348,1350
                          [--outroot <dir>]

Prints one line per dumped tensor: v_id, element count, nan/inf counts,
max|x|, mean|x|. Also flags the FIRST tensor that is not finite.
"""
import argparse
import os
import struct
import subprocess
import sys
import time

ICRAFT_RUN = r"E:\fudanwei\Icraft-3.36.1\bin\icraft-run.exe"


def census(path):
    n = os.path.getsize(path) // 4
    with open(path, "rb") as f:
        a = struct.unpack("<%df" % n, f.read(n * 4))
    nan = inf = 0
    s = 0.0
    mx = 0.0
    for v in a:
        if v != v:
            nan += 1
            continue
        if v == float("inf") or v == float("-inf"):
            inf += 1
            continue
        av = abs(v)
        s += av
        if av > mx:
            mx = av
    fin = n - nan - inf
    return n, nan, inf, mx, (s / fin if fin else 0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qjson", required=True)
    ap.add_argument("--raw", required=True)
    ap.add_argument("--input", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--vids", required=True)
    ap.add_argument("--outroot", default=r"E:\fudanwei\工作区\hostcheck\trace")
    a = ap.parse_args()

    vids = [v.strip() for v in a.vids.split(",") if v.strip()]
    d = os.path.join(a.outroot, a.tag)
    os.makedirs(d, exist_ok=True)
    cmd = [ICRAFT_RUN, "--json", a.qjson, "--raw", a.raw,
           "--input", a.input, "--backends", "Host",
           "--log_path", os.path.join(d, "logs"),
           "--dump_format", "SFB", "--dump_ftmp", ",".join(vids)]
    t0 = time.time()
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=3600)
    txt = p.stdout.decode("utf-8", "replace")
    open(os.path.join(d, "stdout.log"), "w", encoding="utf-8",
         errors="replace").write("CMD: " + " ".join(cmd) + "\n" + txt)
    print("[%s] rc=%d  %.1fs" % (a.tag, p.returncode, time.time() - t0))

    got = {}
    for root, _dirs, files in os.walk(os.path.join(d, "logs")):
        for fn in files:
            if fn.endswith(".ftmp"):
                try:
                    got[int(fn[:-5])] = os.path.join(root, fn)
                except ValueError:
                    pass
    if not got:
        print("   NO DUMPS -- check stdout.log")
        return 1

    first_bad = None
    for v in sorted(got):
        n, nan, inf, mx, mean = census(got[v])
        bad = nan or inf
        if bad and first_bad is None:
            first_bad = v
        print("   v_id=%-6d n=%-8d nan=%-7d inf=%-5d max=%-12.4g mean=%-12.4g %s"
              % (v, n, nan, inf, mx, mean, "<== FIRST NON-FINITE" if bad and first_bad == v else ("BAD" if bad else "")))
    missing = [v for v in vids if int(v) not in got]
    if missing:
        print("   (v_id not present at runtime, skipped by icraft: %s)" % ",".join(missing))
    print("   VERDICT: %s" % ("NaN first at v_id %s" % first_bad if first_bad else "all finite"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
