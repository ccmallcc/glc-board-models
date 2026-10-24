# -*- coding: utf-8 -*-
r"""Dtype variant sweep on the HostBackend.

Quantizes an already-parsed Icraft network with several --qdtype values,
runs each on --backends Host with a fixed .ftmp input, and reports:
  * storage_dtype + compile_target of the first InstanceNorm2d (and a few convs)
  * NaN/Inf census of the dumped intermediate + output tensors
  * max-abs of every dumped tensor

Usage:
  python hb_variant_test.py --parsed <s1_parsed.json> --raw <s1_parsed.raw>
                            --input <input_x.ftmp> --outdir <dir>
                            [--dtypes tf32,bf16,fp16] [--ref <ref.npy>]

Prints a compact table; writes per-variant logs under <outdir>.
"""
import argparse
import json
import os
import re
import struct
import subprocess
import sys
import time

ICRAFT_BIN = r"E:\fudanwei\Icraft-3.36.1\bin"


def run(cmd, log_path, timeout=3600):
    """Run cmd, tee stdout+stderr to log_path. Returns (rc, text)."""
    t0 = time.time()
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=timeout)
    txt = p.stdout.decode("utf-8", "replace")
    with open(log_path, "w", encoding="utf-8", errors="replace") as f:
        f.write("CMD: " + " ".join(cmd) + "\n")
        f.write(txt)
    return p.returncode, txt, time.time() - t0


def short(t):
    if isinstance(t, dict):
        sd = t.get("storage_dtype")
        if sd:
            return short(sd)
        t = t.get("element_dtype")
    if not isinstance(t, str):
        return "?"
    m = re.match(r"@(\w+)\((\d+)\)", t)
    return (m.group(1) + m.group(2)) if m else t


def op_types(net, wanted):
    """op_id -> (type, target, out_dtype) for the first occurrence of each type."""
    got = {}
    for o in net["ops"]:
        t = o.get("_type_key", "").split("::")[-1]
        if t in wanted and t not in got:
            outs = o.get("outputs") or []
            dt = short(outs[0]["dtype"]) if outs else "?"
            got[t] = (o.get("op_id"), o.get("compile_target"), dt)
    return got


def load_ftmp(path):
    n = os.path.getsize(path) // 4
    with open(path, "rb") as f:
        return struct.unpack("<%df" % n, f.read(n * 4))


def census(path):
    a = load_ftmp(path)
    nan = sum(1 for v in a if v != v)
    inf = sum(1 for v in a if v == v and abs(v) == float("inf"))
    fin = [abs(v) for v in a if v == v and abs(v) != float("inf")]
    return len(a), nan, inf, (max(fin) if fin else 0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parsed", required=True)
    ap.add_argument("--raw", required=True)
    ap.add_argument("--input", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--dtypes", default="tf32,bf16,fp16")
    ap.add_argument("--ref_npy", default="")
    ap.add_argument("--probe", default="InstanceNorm2d,Conv2d,SiLU,Multiply")
    a = ap.parse_args()

    os.makedirs(a.outdir, exist_ok=True)
    probe = [t for t in a.probe.split(",") if t]
    rows = []

    for dt in a.dtypes.split(","):
        dt = dt.strip()
        if not dt:
            continue
        tag = dt
        vdir = os.path.join(a.outdir, tag)
        os.makedirs(vdir, exist_ok=True)
        # icraft names outputs after the PARSED json's network name, not the file
        netname = json.load(open(a.parsed, "r", encoding="utf-8")).get("name") or "net"
        qjson = os.path.join(vdir, "%s_quantized.json" % netname)
        qraw = os.path.join(vdir, "%s_quantized.raw" % netname)

        cmd = [os.path.join(ICRAFT_BIN, "icraft-quantize.exe"),
               "--json", a.parsed, "--raw", a.raw, "--jr_path", vdir,
               "--qdtype", dt, "--target", "zhuge",
               "--log_path", os.path.join(vdir, "qlog")]
        rc, txt, secs = run(cmd, os.path.join(vdir, "quantize.stdout.log"))
        print("[%s] quantize rc=%d  %.1fs" % (tag, rc, secs))
        if rc != 0 or not os.path.exists(qjson):
            print("    FAILED:\n" + "\n".join(txt.strip().splitlines()[-12:]))
            rows.append((tag, "quantize-FAIL", "", "", ""))
            continue

        net = json.load(open(qjson, "r", encoding="utf-8"))
        kinds = op_types(net, probe)
        # pick dump v_ids: input, first conv out, second conv out, last two outputs
        vids = []
        for o in net["ops"]:
            t = o.get("_type_key", "").split("::")[-1]
            if t in ("InputNode", "Input"):
                vids.append(o["outputs"][0]["v_id"])
        conv_outs = [o["outputs"][0]["v_id"] for o in net["ops"]
                     if o.get("_type_key", "").endswith("Conv2dNode")]
        vids += conv_outs[:2]
        vids += [o["outputs"][0]["v_id"] for o in net["ops"][-3:]
                 if o.get("outputs")]
        vids = sorted(set(v for v in vids if isinstance(v, int)))

        rdir = os.path.join(vdir, "run")
        os.makedirs(rdir, exist_ok=True)
        cmd = [os.path.join(ICRAFT_BIN, "icraft-run.exe"),
               "--json", qjson, "--raw", qraw,
               "--input", a.input, "--backends", "Host",
               "--log_path", os.path.join(rdir, "logs"),
               "--dump_format", "SFB",
               "--dump_ftmp", ",".join(str(v) for v in vids)]
        rc, txt, secs = run(cmd, os.path.join(vdir, "run.stdout.log"))
        nan_total = inf_total = 0
        maxabs = 0.0
        n_dump = 0
        base = os.path.join(rdir, "logs")
        for root, _dirs, files in os.walk(base):
            for fn in files:
                if not fn.endswith(".ftmp"):
                    continue
                n_dump += 1
                n, nan, inf, mx = census(os.path.join(root, fn))
                nan_total += nan
                inf_total += inf
                maxabs = max(maxabs, mx)
        verdict = "NaN!" if nan_total else ("Inf!" if inf_total else "finite")
        print("    run rc=%d %.1fs  dumps=%d  nan=%d inf=%d max|x|=%.3g  -> %s"
              % (rc, secs, n_dump, nan_total, inf_total, maxabs, verdict))
        for t in probe:
            if t in kinds:
                print("      %-14s op=%-4s target=%-14s out=%s" % ((t,) + kinds[t]))
        rows.append((tag, verdict, "%.3g" % maxabs, str(nan_total), "%.0fs" % secs))

    print("\n===== SUMMARY =====")
    print("%-8s %-14s %-10s %-8s %s" % ("dtype", "verdict", "max|x|", "nan", "time"))
    for r in rows:
        print("%-8s %-14s %-10s %-8s %s" % r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
