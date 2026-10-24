# -*- coding: utf-8 -*-
r"""Canonical Icraft compile pipeline for a GLC subgraph.

Correct stage order (confirmed by experiment 2026-09-12):

    parse -> optimize -> quantize -> adapt -> generate

Skipping `optimize` makes `ZhugePadLayoutPass` inside adapt abort with
"[fatal] vector too long" *even on a one-Conv2d network*; with optimize in
place the whole chain succeeds and generate emits `<name>_ZG.json/.raw`
(HardOp nodes, blocked layouts *C**c16 etc.), structurally identical to the
official 30TAI demo model yolov5s_plin_352x640_ZG.json.

Stages are resumable: an existing output file is reused unless --force.

Usage:
  python c1_pipeline.py --parsed <net_parsed.json> [--raw <...>]
                        --dtype int8|bf16|tf32|fp16
                        --outdir <dir> [--calib_dir D --calib_list L]
                        [--input in.ftmp] [--dump_vids "0,16,36"]
                        [--stages optimize,quantize,adapt,generate,run]
"""
import argparse
import json
import os
import subprocess
import sys
import time

BIN = r"E:\fudanwei\Icraft-3.36.1\bin"


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
    return " || ".join(k.split(":", 1)[-1].strip()[:110] for k in keep[-3:])


def stage(tag, cmd, log, expect):
    if os.path.exists(expect):
        return True, "cached", 0.0, ""
    rc, txt, secs = sh(cmd, log)
    ok = os.path.exists(expect)
    return ok, ("ok" if ok else "FAIL"), secs, err(txt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parsed", required=True)
    ap.add_argument("--raw", default="")
    ap.add_argument("--dtype", default="int8")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--calib_dir", default="")
    ap.add_argument("--calib_list", default="")
    ap.add_argument("--input", default="")
    ap.add_argument("--dump_vids", default="")
    ap.add_argument("--stages", default="optimize,quantize,adapt,generate,run")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--per", default="tensor")
    ap.add_argument("--saturation", default="kld")
    ap.add_argument("--mix_precision", default="",
                    help="path to a mixed-precision CSV; makes forward_dir/"
                         "forward_list/saturation/per mandatory (they are "
                         "passed automatically when --calib_dir is given)")
    ap.add_argument("--keep_optimized_raw", action="store_true",
                    help="keep <name>_optimized.raw (big); default deletes it "
                         "right after quantize since nothing later needs it")
    a = ap.parse_args()

    raw = a.raw or a.parsed.replace("_parsed.json", "_parsed.raw")
    name = json.load(open(a.parsed, encoding="utf-8")).get("name") or "net"
    os.makedirs(a.outdir, exist_ok=True)
    want = [s.strip() for s in a.stages.split(",") if s.strip()]
    report = {"network": name, "dtype": a.dtype, "outdir": a.outdir, "stages": {}}

    def p(suffix):
        return os.path.join(a.outdir, "%s_%s" % (name, suffix))

    opt_j, opt_r = p("optimized.json"), p("optimized.raw")
    q_j, q_r = p("quantized.json"), p("quantized.raw")
    ad_j, ad_r = p("adapted.json"), p("adapted.raw")
    gen_j, gen_r = p("_ZG.json"), p("_ZG.raw")

    if "optimize" in want:
        if a.force:
            for f in (opt_j, opt_r):
                if os.path.exists(f):
                    os.remove(f)
        ok, st, secs, e = stage("optimize",
                                [os.path.join(BIN, "icraft-optimize.exe"),
                                 "--json", a.parsed, "--raw", raw,
                                 "--jr_path", a.outdir, "--target", "zhuge",
                                 "--log_path", os.path.join(a.outdir, "optlog")],
                                os.path.join(a.outdir, "optimize.txt"), opt_j)
        report["stages"]["optimize"] = dict(status=st, secs=round(secs, 1), err=e)
        print("  optimize   %-7s %6.1fs  %s" % (st, secs, e))
        if not ok:
            json.dump(report, open(os.path.join(a.outdir, "pipeline.json"), "w"),
                      ensure_ascii=False, indent=2)
            return 1

    if "quantize" in want:
        if a.force:
            for f in (q_j, q_r):
                if os.path.exists(f):
                    os.remove(f)
        cmd = [os.path.join(BIN, "icraft-quantize.exe"), "--json", opt_j,
               "--raw", opt_r, "--jr_path", a.outdir, "--qdtype", a.dtype,
               "--target", "zhuge", "--log_path", os.path.join(a.outdir, "qlog")]
        if a.dtype == "int8" or a.calib_dir or a.mix_precision:
            cmd += ["--forward_dir", a.calib_dir, "--forward_list", a.calib_list,
                    "--saturation", a.saturation, "--per", a.per,
                    "--no_transinput", "true"]
        if a.mix_precision:
            cmd += ["--mix_precision", a.mix_precision]
        ok, st, secs, e = stage("quantize", cmd,
                                os.path.join(a.outdir, "quantize.txt"), q_j)
        report["stages"]["quantize"] = dict(status=st, secs=round(secs, 1), err=e)
        print("  quantize   %-7s %6.1fs  %s" % (st, secs, e))
        if ok and not a.keep_optimized_raw and os.path.exists(opt_r):
            os.remove(opt_r)
            report["stages"]["optimize"]["note"] = "optimized.raw removed after quantize"
        if not ok:
            json.dump(report, open(os.path.join(a.outdir, "pipeline.json"), "w"),
                      ensure_ascii=False, indent=2)
            return 1

    if "adapt" in want:
        if a.force:
            for f in (ad_j, ad_r):
                if os.path.exists(f):
                    os.remove(f)
        ok, st, secs, e = stage("adapt",
                                [os.path.join(BIN, "icraft-adapt.exe"),
                                 "--json", q_j, "--raw", q_r, "--jr_path", a.outdir,
                                 "--target", "zhuge",
                                 "--log_path", os.path.join(a.outdir, "adaptlog")],
                                os.path.join(a.outdir, "adapt.txt"), ad_j)
        report["stages"]["adapt"] = dict(status=st, secs=round(secs, 1), err=e)
        print("  adapt      %-7s %6.1fs  %s" % (st, secs, e))

    if "generate" in want and os.path.exists(ad_j):
        gn = os.path.join(a.outdir, "gen")
        os.makedirs(gn, exist_ok=True)
        gj = os.path.join(gn, "%s_ZG.json" % name)
        if a.force and os.path.exists(gj):
            os.remove(gj)
        ok, st, secs, e = stage("generate",
                                [os.path.join(BIN, "icraft-generate.exe"),
                                 "--json", ad_j, "--raw", ad_r, "--jr_path", gn,
                                 "--log_path", os.path.join(gn, "log")],
                                os.path.join(a.outdir, "generate.txt"), gj)
        report["stages"]["generate"] = dict(status=st, secs=round(secs, 1), err=e,
                                            artifact=gj if ok else "")
        print("  generate   %-7s %6.1fs  %s" % (st, secs, e))

    if "run" in want and os.path.exists(q_j) and a.input:
        rd = os.path.join(a.outdir, "run")
        os.makedirs(rd, exist_ok=True)
        cmd = [os.path.join(BIN, "icraft-run.exe"), "--json", q_j, "--raw", q_r,
               "--input", a.input, "--backends", "Host",
               "--log_path", os.path.join(rd, "logs"), "--dump_format", "SFB"]
        if a.dump_vids:
            cmd += ["--dump_ftmp", a.dump_vids]
        rc, txt, secs = sh(cmd, os.path.join(a.outdir, "run.txt"))
        e = err(txt)
        report["stages"]["run"] = dict(status="ok" if rc == 0 else "FAIL",
                                       secs=round(secs, 1), rc=rc, err=e)
        print("  run(Host)  %-7s %6.1fs  rc=%d %s"
              % ("ok" if rc == 0 else "FAIL", secs, rc, e))

    json.dump(report, open(os.path.join(a.outdir, "pipeline.json"), "w"),
              ensure_ascii=False, indent=2)
    print("  -> %s" % os.path.join(a.outdir, "pipeline.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
