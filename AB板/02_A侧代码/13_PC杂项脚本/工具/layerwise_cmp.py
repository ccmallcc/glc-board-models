# -*- coding: utf-8 -*-
r"""Layer-wise float-vs-quantized error analysis over an Icraft subgraph.

`icraft-show --ide --compare-stages` does the same thing conceptually but in
CLI mode it only emits the raw dumps (no metrics table), so this script builds
the table itself:

  1. run the fp32 (parsed) network with --dump_output       -> dumps.SFB/
  2. run the quantized network with --dump_output           -> dumps.SFB/
  3. for every v_id present in BOTH dumps, compare element-wise
     (both come from the same graph position and the same runtime layout,
      so a flat element-wise comparison is valid)

Outputs a markdown table sorted by cosine ascending, so the worst layers are
at the top -- these are the ones that need a higher bit width.

Usage:
  python layerwise_cmp.py --sub s2 --dtype int8 [--root DIR] [--top 25]
"""
import argparse
import json
import os
import struct
import subprocess
import sys

import numpy as np

BIN = r"E:\fudanwei\Icraft-3.36.1\bin"
JR = r"E:\fudanwei\工作区\onnx\c1_simple\run"
CAL = r"E:\fudanwei\工作区\calibref\calib"

SUB = {
    "s1": ("s1_encoder_ga_hyper", ["00.ftmp"]),
    "s2": ("s2_hyperdec_fusion", ["00.ftmp"]),
    "s3p1": ("s3_phase1", ["00.ftmp", "00_b.ftmp"]),
    "s4": ("s4_gs_generator", ["00.ftmp"]),
}


def sh(cmd, log):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=7200)
    txt = p.stdout.decode("utf-8", "replace")
    open(log, "w", encoding="utf-8", errors="replace").write(
        "CMD: " + " ".join(cmd) + "\n\n" + txt)
    return p.returncode, txt


def dumps(d):
    """v_id -> path for every .ftmp under d."""
    out = {}
    for root, _dirs, files in os.walk(d):
        for f in files:
            if f.endswith(".ftmp"):
                try:
                    out[int(f[:-5])] = os.path.join(root, f)
                except ValueError:
                    pass
    return out


def load(p):
    n = os.path.getsize(p) // 4
    with open(p, "rb") as f:
        return np.frombuffer(f.read(n * 4), dtype=np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sub", default="s2")
    ap.add_argument("--dtype", default="int8")
    ap.add_argument("--root", default=r"E:\fudanwei\工作区\compile2")
    ap.add_argument("--work", default=r"E:\fudanwei\工作区\layerwise")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--max_layers", type=int, default=0,
                    help="evenly subsample at most this many v_ids (0 = all); "
                         "use for big graphs to bound dump size")
    ap.add_argument("--md", default="")
    a = ap.parse_args()

    name, inps = SUB[a.sub]
    jr = os.path.join(JR, "jr_" + name)
    pj, pr = os.path.join(jr, name + "_parsed.json"), os.path.join(jr, name + "_parsed.raw")
    qd = os.path.join(a.root, "%s_%s" % (a.sub, a.dtype))
    qj, qr = os.path.join(qd, name + "_quantized.json"), os.path.join(qd, name + "_quantized.raw")
    cal = os.path.join(CAL, name)
    inpath = ";".join(os.path.join(cal, i) for i in inps)
    for p in (pj, pr, qj, qr):
        if not os.path.exists(p):
            print("MISSING " + p)
            return 1

    res = {}
    # Runtime v_ids for --dump_ftmp: take the *parsed* graph's op-output ids.
    # Quantization keeps the original ids and only adds Casts with new high
    # ids, so the parsed ids are valid in both graphs (verified on S1: ids
    # 16/28/30/36/48 all dumped in the INT8 graph).
    net = json.load(open(pj, encoding="utf-8"))
    vids = []
    for o in net["ops"]:
        for v in (o.get("outputs") or []):
            if isinstance(v, dict) and isinstance(v.get("v_id"), int):
                vids.append(v["v_id"])
    vids = sorted(set(vids))
    if a.max_layers and len(vids) > a.max_layers:
        step = len(vids) / float(a.max_layers)
        vids = sorted({vids[min(len(vids) - 1, int(i * step))]
                       for i in range(a.max_layers)})
        print("  subsampled to %d v_ids" % len(vids))
    dumpspec = ",".join(str(v) for v in vids)
    print("  parsed graph: %d ops, %d distinct output v_ids" % (len(net["ops"]), len(vids)))

    for tag, js, rw in (("fp32", pj, pr), (a.dtype, qj, qr)):
        d = os.path.join(a.work, "%s_%s_%s" % (a.sub, a.dtype, tag))
        os.makedirs(d, exist_ok=True)
        rc, txt = sh([os.path.join(BIN, "icraft-run.exe"), "--json", js, "--raw", rw,
                      "--input", inpath, "--backends", "Host",
                      "--log_path", os.path.join(d, "logs"),
                      "--dump_format", "SFB", "--dump_ftmp", dumpspec],
                     os.path.join(d, "run.txt"))
        ds = {}
        for root, _dirs, files in os.walk(os.path.join(d, "logs")):
            for f in files:
                if f.endswith(".ftmp"):
                    try:
                        ds[int(f[:-5])] = os.path.join(root, f)
                    except ValueError:
                        pass
        print("  %-5s rc=%d  dumped %d tensors" % (tag, rc, len(ds)))
        res[tag] = ds

    common = sorted(set(res["fp32"]) & set(res[a.dtype]))
    print("  common v_ids: %d" % len(common))
    rows = []
    for v in common:
        x = load(res["fp32"][v])
        y = load(res[a.dtype][v])
        if x.size != y.size or x.size == 0:
            continue
        d = np.abs(x - y)
        nrm = (np.linalg.norm(x) * np.linalg.norm(y))
        cos = float(x @ y / nrm) if nrm > 0 else float("nan")
        mx = float(np.abs(x).max())
        rows.append(dict(v_id=v, n=int(x.size), cos=cos,
                         mae=float(d.mean()),
                         max_abs=float(d.max()),
                         rel=float(d.max() / mx) if mx > 0 else float("nan"),
                         nan=int(np.isnan(y).sum()), inf=int(np.isinf(y).sum())))

    rows.sort(key=lambda r: r["cos"])
    L = []
    L.append("### %s / %s 逐层误差（%d 层可比）" % (name, a.dtype, len(rows)))
    L.append("")
    L.append("| v_id | 元素数 | 余弦 | 平均\\|Δ\\| | 最大\\|Δ\\| | 相对误差 | NaN |")
    L.append("|---|---|---|---|---|---|---|")
    for r in rows[:a.top]:
        L.append("| %d | %d | %.6f | %.3e | %.3e | %.3f | %d |"
                 % (r["v_id"], r["n"], r["cos"], r["mae"], r["max_abs"], r["rel"], r["nan"]))
    if len(rows) > a.top:
        L.append("")
        L.append("（仅列最差 %d 层；共 %d 层）" % (a.top, len(rows)))
    out = "\n".join(L)
    print(out)
    if rows:
        cs = [r["cos"] for r in rows]
        print("\n  余弦：min=%.6f 中位=%.6f max=%.6f" % (min(cs), float(np.median(cs)), max(cs)))
        print("  最差 3 层 v_id: %s" % [r["v_id"] for r in rows[:3]])
    if a.md:
        open(a.md, "w", encoding="utf-8").write(out + "\n")
        print("  written " + a.md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
