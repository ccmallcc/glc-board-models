# -*- coding: utf-8 -*-
r"""Minimal tf32-vs-bf16 Conv2d probe for the Icraft HostBackend.

Builds a one-Conv2d ONNX (128->128, 3x3, pad 1, 256x256), parses it for
zhuge, quantizes it twice (tf32 / bf16), runs both on --backends Host with
one identical random .ftmp input, and compares the conv output statistics.

If tf32 blows up while bf16 stays sane on this single layer, the tf32
Conv2d lowering/emulation itself is at fault (not the model, not the
precision of tf32 in general, since bf16 has a *shorter* mantissa).

Usage:
  python hb_conv_probe.py [--outdir DIR] [--seed 0] [--scale 1.0]

Writes ONNX + ftmp + per-dtype logs under --outdir.
"""
import argparse
import json
import os
import struct
import subprocess
import sys
import time

BIN = r"E:\fudanwei\Icraft-3.36.1\bin"


def sh(cmd, log):
    t0 = time.time()
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=3600)
    txt = p.stdout.decode("utf-8", "replace")
    with open(log, "w", encoding="utf-8", errors="replace") as f:
        f.write("CMD: " + " ".join(cmd) + "\n\n" + txt)
    return p.returncode, txt, time.time() - t0


def census(path):
    n = os.path.getsize(path) // 4
    with open(path, "rb") as f:
        a = struct.unpack("<%df" % n, f.read(n * 4))
    nan = sum(1 for v in a if v != v)
    inf = sum(1 for v in a if v == v and abs(v) == float("inf"))
    fin = [abs(v) for v in a if v == v and abs(v) != float("inf")]
    return n, nan, inf, (max(fin) if fin else 0.0)


def build_onnx(path, scale):
    import torch
    import torch.nn as nn
    torch.manual_seed(0)
    net = nn.Conv2d(128, 128, 3, padding=1, bias=True)
    with torch.no_grad():
        net.weight.mul_(scale)
        net.bias.mul_(scale)
    net.eval()
    dummy = torch.randn(1, 128, 256, 256)
    torch.onnx.export(net, dummy, path, opset_version=17,
                      input_names=["x"], output_names=["y"],
                      dynamic_axes=None)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=r"E:\fudanwei\工作区\hostcheck\convprobe")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--amps", default="25")   # input amplitude(s) to test
    a = ap.parse_args()

    os.makedirs(a.outdir, exist_ok=True)
    onnx_path = os.path.join(a.outdir, "conv_only.onnx")
    build_onnx(onnx_path, a.scale)
    print("built %s (%d bytes)" % (onnx_path, os.path.getsize(onnx_path)))

    jr = os.path.join(a.outdir, "jr")
    os.makedirs(jr, exist_ok=True)
    # pre_mean / pre_scale must be per-channel vectors (size == input C)
    C = 128
    cmd = [os.path.join(BIN, "icraft-parse.exe"), "--net_name", "convonly",
           "--network", onnx_path, "--jr_path", jr,
           "--log_path", os.path.join(a.outdir, "plog"),
           "--framework", "ONNX", "--frame_version", "opset17", "--target", "zhuge",
           "--inputs_dtype", "FP32", "--inputs", "1,256,256,128",
           "--inputs_layout", "NHWC",
           "--pre_method", "nop",
           "--pre_scale", ",".join(["1.0"] * C),
           "--pre_mean", ",".join(["0.0"] * C),
           "--channel_swap", ",".join(str(i) for i in range(C))]
    rc, txt, secs = sh(cmd, os.path.join(a.outdir, "parse.stdout.log"))
    pj = os.path.join(jr, "convonly_parsed.json")
    print("parse rc=%d %.1fs -> %s" % (rc, secs, os.path.exists(pj)))
    if not os.path.exists(pj):
        print("\n".join(txt.strip().splitlines()[-15:]))
        return 1

    import random
    for amp in [float(x) for x in a.amps.split(",")]:
        random.seed(a.seed)
        n = 1 * 256 * 256 * 128
        ftmp = os.path.join(a.outdir, "in_amp%g.ftmp" % amp)
        with open(ftmp, "wb") as f:
            f.write(struct.pack("<%df" % n,
                                *[random.uniform(-amp, amp) for _ in range(n)]))
        print("\n--- input amplitude %.4g  (%s) ---" % (amp, ftmp))

        for dt in ("tf32", "bf16", "fp16"):
            vdir = os.path.join(a.outdir, "amp%g" % amp, dt)
            os.makedirs(vdir, exist_ok=True)
            qj = os.path.join(vdir, "convonly_quantized.json")
            qr = os.path.join(vdir, "convonly_quantized.raw")
            rc, txt, secs = sh(
                [os.path.join(BIN, "icraft-quantize.exe"),
                 "--json", pj, "--raw", os.path.join(jr, "convonly_parsed.raw"),
                 "--jr_path", vdir, "--qdtype", dt, "--target", "zhuge",
                 "--log_path", os.path.join(vdir, "qlog")],
                os.path.join(vdir, "quantize.stdout.log"))
            if not os.path.exists(qj):
                print("  %-5s quantize FAILED" % dt)
                continue
            rd = os.path.join(vdir, "run")
            os.makedirs(rd, exist_ok=True)
            rc, txt, secs = sh(
                [os.path.join(BIN, "icraft-run.exe"),
                 "--json", qj, "--raw", qr, "--input", ftmp,
                 "--backends", "Host", "--log_path", os.path.join(rd, "logs"),
                 "--dump_format", "SFB", "--dump_ftmp", "0,2"],
                os.path.join(vdir, "run.stdout.log"))
            stats = []
            for root, _d, files in os.walk(os.path.join(rd, "logs")):
                for fn in sorted(files):
                    if fn.endswith(".ftmp"):
                        nn_, nan, inf, mx = census(os.path.join(root, fn))
                        stats.append("%s:n=%d nan=%d inf=%d max=%.4g"
                                     % (fn[:-5], nn_, nan, inf, mx))
            print("  %-5s rc=%d %5.1fs  %s" % (dt, rc, secs, " | ".join(stats)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
