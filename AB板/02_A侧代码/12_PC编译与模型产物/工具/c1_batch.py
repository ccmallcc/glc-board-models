# -*- coding: utf-8 -*-
r"""Compile + score every GLC subgraph with the canonical Icraft pipeline.

For each (subgraph, dtype):
    optimize -> quantize -> adapt -> generate
then run on --backends Host with --log_io, learn the true runtime v_ids of the
Output op from the io log, dump those tensors and score them against the fp32
PyTorch references produced by c1_make_calib_refs.py.

Output v_ids cannot be hard-coded: icraft renumbers values between the parsed,
quantized and runtime graphs.

Usage:
  python c1_batch.py --dtypes int8,bf16 [--subs s1,s2,s3,s4]
                     [--root E:\fudanwei\工作区\compile2]
                     [--stages optimize,quantize,adapt,generate,run]
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
JR = r"E:\fudanwei\工作区\onnx\c1_simple\run"
# CAL / REF are now derived from --calib_root in main()

# subgraph -> (parsed name, [ (input ftmp name in calib dir), ... ],
#             [ (output label, NHWC shape, ref template), ... ], multi_input)
SUBS = {
    "s1": ("s1_encoder_ga_hyper", ["00.ftmp"],
           [("y", (1, 16, 16, 256), "s1_y_00.npy"),
            ("z", (1, 4, 4, 256), "s1_z_00.npy")], False),
    "s2": ("s2_hyperdec_fusion", ["00.ftmp"],
           [("common_params", (1, 16, 16, 768), "s2_params_00.npy")], False),
    "s3p1": ("s3_phase1", ["00.ftmp", "00_b.ftmp"],
             [("scales", (1, 16, 16, 256), "s3p1_scales_00.npy"),
              ("means", (1, 16, 16, 256), "s3p1_means_00.npy")], True),
    "s3p2": ("s3_phase2", ["00.ftmp", "00_b.ftmp"],
             [("scales", (1, 16, 16, 256), "s3p2_scales_00.npy"),
              ("means", (1, 16, 16, 256), "s3p2_means_00.npy")], True),
    "s3p3": ("s3_phase3", ["00.ftmp", "00_b.ftmp"],
             [("scales", (1, 16, 16, 256), "s3p3_scales_00.npy"),
              ("means", (1, 16, 16, 256), "s3p3_means_00.npy")], True),
    "s4": ("s4_gs_generator", ["00.ftmp"],
           [("x_hat", (1, 256, 256, 3), "s4_xhat_00.npy")], False),
}


def sh(cmd, log):
    t0 = time.time()
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=7200)
    txt = p.stdout.decode("utf-8", "replace")
    with open(log, "w", encoding="utf-8", errors="replace") as f:
        f.write("CMD: " + " ".join(cmd) + "\n\n" + txt)
    return p.returncode, txt, time.time() - t0


def err(txt):
    keep = [s.strip() for s in txt.replace("\r", "\n").split("\n")
            if "Exception info" in s or "Check failed" in s or "[fatal]" in s]
    return " || ".join(k.split(":", 1)[-1].strip()[:100] for k in keep[-2:])


def run_stage(cmd, log, expect, force):
    if os.path.exists(expect) and not force:
        return "cached", 0.0, ""
    rc, txt, secs = sh(cmd, log)
    return ("ok" if os.path.exists(expect) else "FAIL"), secs, err(txt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dtypes", default="int8,bf16")
    ap.add_argument("--subs", default="s1,s2,s3p1,s3p2,s3p3,s4")
    ap.add_argument("--root", default=r"E:\fudanwei\工作区\compile2")
    ap.add_argument("--stages", default="optimize,quantize,adapt,generate,run")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--per", default="tensor")
    ap.add_argument("--calib_root", default=r"E:\fudanwei\工作区\calibref",
                    help="directory holding calib/<sub>/ and refs/ (see "
                         "c1_make_calib_refs.py)")
    ap.add_argument("--eval_root", default="",
                    help="directory holding the *held-out* inputs+refs used for "
                         "the HostBackend run and scoring. Defaults to "
                         "--calib_root, but for an honest quantization A/B you "
                         "want calibration and evaluation on different images.")
    ap.add_argument("--sample", default="00",
                    help="which calibration index to use for the HostBackend run "
                         "and the scoring reference")
    a = ap.parse_args()
    want = [s.strip() for s in a.stages.split(",") if s.strip()]
    rows = []
    CAL = os.path.join(a.calib_root, "calib")
    REF = os.path.join(a.calib_root, "refs")
    EVAL = os.path.join(a.eval_root, "calib") if a.eval_root else CAL
    EREF = os.path.join(a.eval_root, "refs") if a.eval_root else REF
    SMP = a.sample
    print("calib_root = %s" % a.calib_root)
    print("eval_root  = %s   sample = %s" % (a.eval_root or "(= calib_root)", SMP))

    for sk in [s.strip() for s in a.subs.split(",") if s.strip()]:
        name, inp_names, outs, multi = SUBS[sk]
        inp_names = [n.replace("00", SMP) if n.startswith("00") else n
                     for n in inp_names]
        outs = [(lbl, shp, rt.replace("_00.", "_%s." % SMP)) for lbl, shp, rt in outs]
        pj = os.path.join(JR, "jr_" + name, name + "_parsed.json")
        pr = pj.replace("_parsed.json", "_parsed.raw")
        cal_dir = os.path.join(CAL, name)
        cal_list = os.path.join(cal_dir, "list.txt")
        ev_dir = os.path.join(EVAL, name)
        inpath = ";".join(os.path.join(ev_dir, n) for n in inp_names)

        for dt in [d.strip() for d in a.dtypes.split(",") if d.strip()]:
            out = os.path.join(a.root, "%s_%s" % (sk, dt))
            os.makedirs(out, exist_ok=True)
            print("=" * 78)
            print("### %-6s %-5s -> %s" % (sk, dt, out))
            rec = {"sub": sk, "name": name, "dtype": dt, "stages": {}}
            j = lambda suf: os.path.join(out, "%s_%s" % (name, suf))
            opt_j, opt_r = j("optimized.json"), j("optimized.raw")
            q_j, q_r = j("quantized.json"), j("quantized.raw")
            ad_j, ad_r = j("adapted.json"), j("adapted.raw")
            gen_j = os.path.join(out, "gen", "%s_ZG.json" % name)

            if "optimize" in want:
                st, secs, e = run_stage(
                    [os.path.join(BIN, "icraft-optimize.exe"), "--json", pj,
                     "--raw", pr, "--jr_path", out, "--target", "zhuge",
                     "--log_path", os.path.join(out, "optlog")],
                    os.path.join(out, "optimize.txt"), opt_j, a.force)
                print("  optimize   %-7s %6.1fs %s" % (st, secs, e))
                rec["stages"]["optimize"] = dict(status=st, secs=round(secs, 1), err=e)
                if st == "FAIL":
                    rows.append(rec)
                    break

            if "quantize" in want:
                cmd = [os.path.join(BIN, "icraft-quantize.exe"), "--json", opt_j,
                       "--raw", opt_r, "--jr_path", out, "--qdtype", dt,
                       "--target", "zhuge", "--log_path", os.path.join(out, "qlog")]
                if dt == "int8":
                    cmd += ["--forward_dir", cal_dir, "--forward_list", cal_list,
                            "--saturation", "kld", "--per", a.per,
                            "--no_transinput", "true"]
                st, secs, e = run_stage(cmd, os.path.join(out, "quantize.txt"),
                                        q_j, a.force)
                print("  quantize   %-7s %6.1fs %s" % (st, secs, e))
                rec["stages"]["quantize"] = dict(status=st, secs=round(secs, 1), err=e)
                if st == "FAIL":
                    rows.append(rec)
                    break
                if os.path.exists(opt_r):
                    os.remove(opt_r)

            if "adapt" in want:
                st, secs, e = run_stage(
                    [os.path.join(BIN, "icraft-adapt.exe"), "--json", q_j,
                     "--raw", q_r, "--jr_path", out, "--target", "zhuge",
                     "--log_path", os.path.join(out, "adaptlog")],
                    os.path.join(out, "adapt.txt"), ad_j, a.force)
                print("  adapt      %-7s %6.1fs %s" % (st, secs, e))
                rec["stages"]["adapt"] = dict(status=st, secs=round(secs, 1), err=e)

            if "generate" in want and os.path.exists(ad_j):
                gn = os.path.join(out, "gen")
                os.makedirs(gn, exist_ok=True)
                st, secs, e = run_stage(
                    [os.path.join(BIN, "icraft-generate.exe"), "--json", ad_j,
                     "--raw", ad_r, "--jr_path", gn,
                     "--log_path", os.path.join(gn, "log")],
                    os.path.join(out, "generate.txt"), gen_j, a.force)
                sz = os.path.getsize(gen_j) if os.path.exists(gen_j) else 0
                print("  generate   %-7s %6.1fs json=%d B  %s" % (st, secs, sz, e))
                rec["stages"]["generate"] = dict(status=st, secs=round(secs, 1),
                                                 bytes=sz, err=e)

            if "run" in want and os.path.exists(q_j):
                rd = os.path.join(out, "run")
                os.makedirs(rd, exist_ok=True)
                rc, txt, secs = sh(
                    [os.path.join(BIN, "icraft-run.exe"), "--json", q_j,
                     "--raw", q_r, "--input", inpath, "--backends", "Host",
                     "--log_path", os.path.join(rd, "logs"), "--log_io"],
                    os.path.join(out, "run_io.txt"))
                iolog = None
                for root, _d, fs in os.walk(os.path.join(rd, "logs")):
                    for f in fs:
                        if f.endswith("_run_io.log"):
                            iolog = os.path.join(root, f)
                vids = []
                if iolog:
                    for ln in open(iolog, encoding="utf-8", errors="replace"):
                        if re.match(r"\s*Output\b", ln):
                            vids = [int(m) for m in re.findall(r"\((\d+)\|", ln)]
                print("  run(Host)  %-7s %6.1fs rc=%d  io_log=%s  out_vids=%s %s"
                      % ("ok" if rc == 0 else "FAIL", secs, rc,
                         os.path.basename(iolog) if iolog else "none", vids, err(txt)))
                rec["stages"]["run"] = dict(status="ok" if rc == 0 else "FAIL",
                                            secs=round(secs, 1), rc=rc,
                                            out_vids=vids, err=err(txt))

                if rc == 0 and len(vids) == len(outs):
                    dd = os.path.join(out, "run_out")
                    os.makedirs(dd, exist_ok=True)
                    sh([os.path.join(BIN, "icraft-run.exe"), "--json", q_j,
                        "--raw", q_r, "--input", inpath, "--backends", "Host",
                        "--log_path", os.path.join(dd, "logs"),
                        "--dump_format", "SFB",
                        "--dump_ftmp", ",".join(str(v) for v in vids)],
                       os.path.join(out, "run_dump.txt"))
                    sc = {}
                    for (label, shp, reft), vid in zip(outs, vids):
                        for root, _d, fs in os.walk(os.path.join(dd, "logs")):
                            fp = os.path.join(root, "%d.ftmp" % vid)
                            if not os.path.exists(fp):
                                continue
                            ic = np.fromfile(fp, dtype=np.float32).reshape(shp)
                            ic = np.transpose(ic, (0, 3, 1, 2))
                            ref = np.load(os.path.join(EREF, reft))
                            d = np.abs(ic - ref)
                            cos = float((ic.ravel() @ ref.ravel()) /
                                        (np.linalg.norm(ic) * np.linalg.norm(ref) + 1e-12))
                            sc[label] = dict(v_id=vid, cosine=round(cos, 8),
                                             max_abs=float(d.max()),
                                             mean_abs=float(d.mean()),
                                             ref_max=float(np.abs(ref).max()))
                            print("     %-14s v_id=%-6d cosine=%.7f max|d|=%.4e mean|d|=%.4e"
                                  % (label, vid, cos, d.max(), d.mean()))
                    rec["scores"] = sc
            rows.append(rec)
            json.dump(rows, open(os.path.join(a.root, "batch_summary.json"), "w"),
                      ensure_ascii=False, indent=2)

    print("\n" + "=" * 78)
    print("SUMMARY  (cosine vs fp32 PyTorch reference)")
    for rec in rows:
        s = rec.get("scores", {})
        st = rec.get("stages", {})
        g = st.get("generate", {}).get("status", "-")
        r = st.get("run", {}).get("status", "-")
        txt = "  ".join("%s=%.5f" % (k, v["cosine"]) for k, v in s.items())
        print("  %-6s %-5s gen=%-7s run=%-7s %s" % (rec["sub"], rec["dtype"], g, r, txt))
    return 0


if __name__ == "__main__":
    sys.exit(main())
