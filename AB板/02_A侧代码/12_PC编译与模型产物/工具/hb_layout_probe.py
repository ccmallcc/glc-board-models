# -*- coding: utf-8 -*-
r"""Does a genuinely-NHWC ONNX survive adapt/generate on the zhuge target?

Hypothesis under test
---------------------
`icraft-adapt --target zhuge` always crashes inside ZhugePadLayoutPass with
"vector too long".  One candidate cause is an input-layout mismatch: we
declare `--inputs H,W,C --inputs_layout NHWC` while the ONNX itself is NCHW.
The official 30TAI demo model (yolov5s_plin_352x640_ZG.json) has
`Input layout=@layout(NHWC) shape=[1,352,640,3]`, so NHWC is the expected
convention -- but whether the *source ONNX* must already be channels-last is
untested.

This script exports the same single 3x3 Conv2d twice:
  A) plain NCHW  graph, input [1,C,H,W]
  B) wrapped so the graph input is NHWC [1,H,W,C] (permutes around the conv)
then runs parse -> quantize(bf16) -> adapt -> generate on each and reports
where each stage fails.  bf16 needs no calibration set.

Usage:
  python hb_layout_probe.py [--outdir DIR] [--C 32] [--H 64] [--W 64]
"""
import argparse
import json
import os
import subprocess
import sys
import time

BIN = r"E:\fudanwei\Icraft-3.36.1\bin"


def run(cmd, log, cwd=None):
    t0 = time.time()
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=3600, cwd=cwd)
    txt = p.stdout.decode("utf-8", "replace")
    with open(log, "w", encoding="utf-8", errors="replace") as f:
        f.write("CMD: " + " ".join(cmd) + "\n\n" + txt)
    return p.returncode, txt, time.time() - t0


def err_of(txt):
    keep = []
    for ln in txt.replace("\r", "\n").split("\n"):
        s = ln.strip()
        if "Exception info" in s or "Check failed" in s:
            keep.append(s.split(":", 1)[-1].strip()[:160])
    return " | ".join(keep[-2:]) if keep else ""


def build(path, nhwc, C, H, W):
    import torch
    import torch.nn as nn
    torch.manual_seed(0)
    conv = nn.Conv2d(C, C, 3, padding=1)
    conv.eval()

    class Plain(nn.Module):
        def __init__(self):
            super().__init__()
            self.c = conv

        def forward(self, x):
            return self.c(x)

    class Wrap(nn.Module):
        def __init__(self):
            super().__init__()
            self.c = conv

        def forward(self, x):                 # x: (1,H,W,C)
            y = x.permute(0, 3, 1, 2).contiguous()
            y = self.c(y)
            return y.permute(0, 2, 3, 1).contiguous()

    m = Wrap() if nhwc else Plain()
    dummy = torch.randn(1, H, W, C) if nhwc else torch.randn(1, C, H, W)
    torch.onnx.export(m, dummy, path, opset_version=17,
                      input_names=["x"], output_names=["y"])
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=r"E:\fudanwei\工作区\hostcheck\layoutprobe")
    ap.add_argument("--C", type=int, default=32)
    ap.add_argument("--H", type=int, default=64)
    ap.add_argument("--W", type=int, default=64)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)

    for tag, nhwc in (("A_nchw", False), ("B_nhwc", True)):
        d = os.path.join(a.outdir, tag)
        os.makedirs(d, exist_ok=True)
        onnx = build(os.path.join(d, "m.onnx"), nhwc, a.C, a.H, a.W)
        # declared ftmp dims follow the convention "channel-last order"
        dims = "1,%d,%d,%d" % (a.H, a.W, a.C)
        print("=== %s  onnx_input=%s  declared=%s NHWC" %
              (tag, "NHWC" if nhwc else "NCHW", dims))

        jr = os.path.join(d, "jr")
        os.makedirs(jr, exist_ok=True)
        rc, txt, secs = run(
            [os.path.join(BIN, "icraft-parse.exe"), "--net_name", "m",
             "--network", onnx, "--jr_path", jr, "--log_path",
             os.path.join(d, "plog"), "--framework", "ONNX",
             "--frame_version", "opset17", "--target", "zhuge",
             "--inputs_dtype", "FP32", "--inputs", dims,
             "--inputs_layout", "NHWC",
             "--pre_method", "nop",
             "--pre_scale", ",".join(["1.0"] * a.C),
             "--pre_mean", ",".join(["0.0"] * a.C),
             "--channel_swap", ",".join(str(i) for i in range(a.C))],
            os.path.join(d, "parse.txt"))
        pj = os.path.join(jr, "m_parsed.json")
        print("   parse   rc=%d %5.1fs  %s  %s" % (rc, secs, os.path.exists(pj), err_of(txt)))
        if not os.path.exists(pj):
            continue
        net = json.load(open(pj, encoding="utf-8"))
        ins = [o for o in net["ops"] if o.get("_type_key", "").endswith("Input")]
        if ins:
            v = ins[0]["outputs"][0]["dtype"]
            print("   parsed Input layout=%s shape=%s" % (v.get("layout"), v.get("shape")))

        rc, txt, secs = run(
            [os.path.join(BIN, "icraft-quantize.exe"), "--json", pj,
             "--raw", os.path.join(jr, "m_parsed.raw"), "--jr_path", d,
             "--qdtype", "bf16", "--target", "zhuge",
             "--log_path", os.path.join(d, "qlog")],
            os.path.join(d, "quantize.txt"))
        qj = os.path.join(d, "m_quantized.json")
        print("   quant   rc=%d %5.1fs  %s  %s" % (rc, secs, os.path.exists(qj), err_of(txt)))
        if not os.path.exists(qj):
            continue

        for label, extra in (("adapt", []), ("adapt_off", ["--pass_off", "icraft.ZhugePadLayoutPass"])):
            ad = os.path.join(d, label)
            os.makedirs(ad, exist_ok=True)
            rc, txt, secs = run(
                [os.path.join(BIN, "icraft-adapt.exe"), "--json", qj,
                 "--raw", os.path.join(d, "m_quantized.raw"), "--jr_path", ad,
                 "--target", "zhuge", "--log_path", os.path.join(ad, "log")] + extra,
                os.path.join(d, label + ".txt"))
            ok = os.path.exists(os.path.join(ad, "m_adapted.json"))
            print("   %-9s rc=%-4d %5.1fs  json=%s  %s" % (label, rc, secs, ok, err_of(txt)))
            if ok and label == "adapt":
                gn = os.path.join(d, "gen")
                os.makedirs(gn, exist_ok=True)
                rc, txt, secs = run(
                    [os.path.join(BIN, "icraft-generate.exe"),
                     "--json", os.path.join(ad, "m_adapted.json"),
                     "--raw", os.path.join(ad, "m_adapted.raw"),
                     "--jr_path", gn, "--log_path", os.path.join(gn, "log")],
                    os.path.join(d, "generate.txt"))
                outs = []
                for root, _dd, fs in os.walk(gn):
                    outs += [f for f in fs if f.endswith((".json", ".raw"))]
                print("   generate  rc=%-4d %5.1fs  outputs=%s  %s"
                      % (rc, secs, outs, err_of(txt)))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
