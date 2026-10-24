# -*- coding: utf-8 -*-
r"""V4: redo the key numerical comparisons against the DEPLOYABLE artifact.

`icraft-generate` does not preserve numerics: earlier measurements showed the
`_ZG` output differs from the *quantized graph* output by ~3.5x the quantization
error itself (s2/BF16: mean|d| 1.53e-03 -> 5.44e-03).  Everything we verified
numerically up to now was measured on `*_quantized.json`, i.e. NOT on the thing
that actually ships.

This script runs BOTH graphs through HostBackend on the same held-out input and
scores them against the same fp32 reference, so the three quantities are
separable:

    quantized vs fp32     the quantization error
    _ZG       vs fp32     what the board will actually produce
    _ZG       vs quantized the cost of the `generate` stage

Usage:
  python v4_zg_compare.py --subs s1,s2 --dtypes bf16,int8 \
      --root 工作区\compile2 --eval_root 工作区\calibref_kodak --sample 00
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

import numpy as np

BIN = r"E:\fudanwei\Icraft-3.36.1\bin"

SUBS = {
    "s1": ("s1_encoder_ga_hyper", ["00.ftmp"],
           [("y", (1, 16, 16, 256), "s1_y_00.npy"),
            ("z", (1, 4, 4, 256), "s1_z_00.npy")]),
    "s2": ("s2_hyperdec_fusion", ["00.ftmp"],
           [("common_params", (1, 16, 16, 768), "s2_params_00.npy")]),
}


def sh(cmd, log):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=7200)
    txt = p.stdout.decode("utf-8", "replace")
    with open(log, "w", encoding="utf-8", errors="replace") as f:
        f.write("CMD: " + " ".join(cmd) + "\n\n" + txt)
    return p.returncode, txt


def run_and_dump(jr_json, jr_raw, inpath, workdir, label, n_out):
    """Run a network on HostBackend, learn its Output v_ids, dump them."""
    os.makedirs(workdir, exist_ok=True)
    rc, _ = sh([os.path.join(BIN, "icraft-run.exe"), "--json", jr_json,
                "--raw", jr_raw, "--input", inpath, "--backends", "Host",
                "--log_path", os.path.join(workdir, "logs"), "--log_io"],
               os.path.join(workdir, "io.txt"))
    iolog = None
    for root, _d, fs in os.walk(os.path.join(workdir, "logs")):
        for f in fs:
            if f.endswith("_run_io.log"):
                iolog = os.path.join(root, f)
    vids = []
    if iolog:
        for ln in open(iolog, encoding="utf-8", errors="replace"):
            if re.match(r"\s*Output\b", ln):
                vids = [int(m) for m in re.findall(r"\((\d+)\|", ln)]
    if rc != 0 or len(vids) != n_out:
        return None, "rc=%d vids=%s (want %d) for %s" % (rc, vids, n_out, label)
    dd = os.path.join(workdir, "dump")
    os.makedirs(dd, exist_ok=True)
    sh([os.path.join(BIN, "icraft-run.exe"), "--json", jr_json, "--raw", jr_raw,
        "--input", inpath, "--backends", "Host",
        "--log_path", os.path.join(dd, "logs"), "--dump_format", "SFB",
        "--dump_ftmp", ",".join(str(v) for v in vids)],
       os.path.join(workdir, "dump.txt"))
    out = {}
    for root, _d, fs in os.walk(os.path.join(dd, "logs")):
        for f in fs:
            if f.endswith(".ftmp"):
                out[int(os.path.splitext(f)[0])] = os.path.join(root, f)
    return (vids, out), None


def score(got_nhwc, ref_nchw):
    ic = np.transpose(got_nhwc, (0, 3, 1, 2))
    d = np.abs(ic - ref_nchw)
    cos = float((ic.ravel() @ ref_nchw.ravel()) /
                (np.linalg.norm(ic) * np.linalg.norm(ref_nchw) + 1e-12))
    return cos, float(d.mean()), float(d.max())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subs", default="s1,s2")
    ap.add_argument("--dtypes", default="bf16,int8")
    ap.add_argument("--root", default=r"E:\fudanwei\工作区\compile2")
    ap.add_argument("--eval_root", default=r"E:\fudanwei\工作区\calibref_kodak")
    ap.add_argument("--sample", default="00")
    ap.add_argument("--out", default=r"E:\fudanwei\工作区\v4")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    rows = []
    for sk in [s.strip() for s in a.subs.split(",") if s.strip()]:
        name, inp_names, outs = SUBS[sk]
        inp_names = [n.replace("00", a.sample) for n in inp_names]
        outs = [(l, s, r.replace("_00.", "_%s." % a.sample)) for l, s, r in outs]
        inpath = ";".join(os.path.join(a.eval_root, "calib", name, n)
                          for n in inp_names)
        for dt in [d.strip() for d in a.dtypes.split(",") if d.strip()]:
            out = os.path.join(a.root, "%s_%s" % (sk, dt))
            qj = os.path.join(out, "%s_quantized.json" % name)
            qr = os.path.join(out, "%s_quantized.raw" % name)
            zj = os.path.join(out, "gen", "%s_ZG.json" % name)
            zr = os.path.join(out, "gen", "%s_ZG.raw" % name)
            print("=" * 74)
            print("### %-4s %-5s" % (sk, dt))
            for p in (qj, qr, zj, zr):
                if not os.path.exists(p):
                    print("   missing %s" % p)
            if not all(os.path.exists(p) for p in (qj, qr, zj, zr)):
                continue

            q, e1 = run_and_dump(qj, qr, inpath, os.path.join(a.out, "%s_%s_q" % (sk, dt)),
                                 "quantized", len(outs))
            z, e2 = run_and_dump(zj, zr, inpath, os.path.join(a.out, "%s_%s_zg" % (sk, dt)),
                                 "ZG", len(outs))
            if e1 or e2:
                print("   run failed: %s %s" % (e1, e2))
                continue

            for (label, shp, reft), qv, zv in zip(outs, q[0], z[0]):
                ref = np.load(os.path.join(a.eval_root, "refs", reft))
                qa = np.fromfile(q[1][qv], dtype=np.float32).reshape(shp)
                za = np.fromfile(z[1][zv], dtype=np.float32).reshape(shp)
                c1, m1, x1 = score(qa, ref)
                c2, m2, x2 = score(za, ref)
                c3, m3, x3 = score(za, np.transpose(qa, (0, 3, 1, 2)))
                penalty = (m2 / m1) if m1 > 0 else float("nan")
                rows.append(dict(sub=sk, dtype=dt, out=label,
                                 cos_quant=c1, mean_quant=m1, max_quant=x1,
                                 cos_zg=c2, mean_zg=m2, max_zg=x2,
                                 cos_zg_vs_quant=c3, mean_zg_vs_quant=m3,
                                 generate_penalty=penalty))
                print("   %-14s quant vs fp32 : cos=%.8f mean|d|=%.4e" % (label, c1, m1))
                print("   %-14s _ZG   vs fp32 : cos=%.8f mean|d|=%.4e   (%.2fx the quant error)"
                      % ("", c2, m2, penalty))
                print("   %-14s _ZG   vs quant: cos=%.8f mean|d|=%.4e" % ("", c3, m3))

    json.dump(rows, open(os.path.join(a.out, "v4_results.json"), "w",
                         encoding="utf-8"), ensure_ascii=False, indent=2)
    print("\n-> %s" % os.path.join(a.out, "v4_results.json"))
    if rows:
        print("\n%-4s %-5s %-14s %14s %14s %8s" %
              ("sub", "dtype", "output", "mean|d| quant", "mean|d| _ZG", "penalty"))
        for r in rows:
            print("%-4s %-5s %-14s %14.4e %14.4e %7.2fx" %
                  (r["sub"], r["dtype"], r["out"], r["mean_quant"], r["mean_zg"],
                   r["generate_penalty"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
