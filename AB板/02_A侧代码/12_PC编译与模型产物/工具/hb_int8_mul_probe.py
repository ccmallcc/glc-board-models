# -*- coding: utf-8 -*-
r"""Minimal reproduction of the INT8 zhuge HostBackend `Multiply` crash.

Finding under test
------------------
`icraft-run --backends Host` on an INT8-quantized GLC encoder subgraph dies in

    Op N icraft::xir::MultiplyNode forward failed.
    Index 1 out of bounds 1
    <- zgi::VpeRoutInst::setXvlen_en
    <- icraft-hostbackend/ops/zhuge/multiply.cpp:183

The GLC graph contains 13 `Mul(tensor, scalar-constant)` nodes (torch's
GroupNorm/SiLU decomposition), so the hypothesis is that the zhuge VPE
emulation breaks when the const operand has exactly one element.

Variants built and pushed through parse -> quantize(int8) -> run(Host):
  A) y = x * 0.5                      scalar const, shape ()
  B) y = x * ones(C,1,1)*0.5          per-channel const, shape (C,1,1)
  C) y = x + x                        no const mul at all (control)

Usage:
  python hb_int8_mul_probe.py [--outdir DIR] [--C 32] [--H 64] [--W 64]
"""
import argparse
import os
import subprocess
import sys
import time

import numpy as np

BIN = r"E:\fudanwei\Icraft-3.36.1\bin"


def run(cmd, log, cwd=None):
    t0 = time.time()
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=3600, cwd=cwd)
    txt = p.stdout.decode("utf-8", "replace")
    open(log, "w", encoding="utf-8", errors="replace").write(
        "CMD: " + " ".join(cmd) + "\n\n" + txt)
    return p.returncode, txt, time.time() - t0


def err_of(txt):
    keep = [s.strip() for s in txt.replace("\r", "\n").split("\n")
            if "Exception info" in s or "Check failed" in s]
    return " | ".join(k.split(":", 1)[-1].strip()[:120] for k in keep[-2:])


def build(path, kind, C, H, W):
    import torch
    import torch.nn as nn

    class M(nn.Module):
        def __init__(self):
            super().__init__()
            self.kind = kind
            if kind == "scalar":
                self.register_buffer("k", torch.tensor(0.5))
            elif kind == "channel":
                self.register_buffer("k", torch.full((C, 1, 1), 0.5))

        def forward(self, x):
            if self.kind == "scalar":
                return x * self.k
            if self.kind == "channel":
                return x * self.k
            return x + x

    torch.onnx.export(M(), torch.randn(1, C, H, W), path, opset_version=17,
                      input_names=["x"], output_names=["y"])
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=r"E:\fudanwei\工作区\hostcheck\mulprobe")
    ap.add_argument("--C", type=int, default=32)
    ap.add_argument("--H", type=int, default=64)
    ap.add_argument("--W", type=int, default=64)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)

    # calibration binaries: NHWC float32, 4 samples
    cal = os.path.join(a.outdir, "calib")
    os.makedirs(cal, exist_ok=True)
    names = []
    rng = np.random.default_rng(0)
    for i in range(4):
        fn = "c%d.ftmp" % i
        rng.uniform(-1, 1, size=(1, a.H, a.W, a.C)).astype(np.float32).tofile(
            os.path.join(cal, fn))
        names.append(fn)
    lst = os.path.join(cal, "list.txt")
    open(lst, "w").write("\n".join(names) + "\n")

    inp = os.path.join(a.outdir, "in.ftmp")
    rng.uniform(-1, 1, size=(1, a.H, a.W, a.C)).astype(np.float32).tofile(inp)

    dims = "1,%d,%d,%d" % (a.H, a.W, a.C)
    for kind in ("scalar", "channel", "add"):
        d = os.path.join(a.outdir, kind)
        os.makedirs(d, exist_ok=True)
        onnx = build(os.path.join(d, "m.onnx"), kind if kind != "add" else "add",
                     a.C, a.H, a.W)
        jr = os.path.join(d, "jr")
        os.makedirs(jr, exist_ok=True)
        rc, txt, secs = run(
            [os.path.join(BIN, "icraft-parse.exe"), "--net_name", "m",
             "--network", onnx, "--jr_path", jr, "--log_path", os.path.join(d, "plog"),
             "--framework", "ONNX", "--frame_version", "opset17",
             "--target", "zhuge", "--inputs_dtype", "FP32", "--inputs", dims,
             "--inputs_layout", "NHWC", "--pre_method", "nop",
             "--pre_scale", ",".join(["1.0"] * a.C),
             "--pre_mean", ",".join(["0.0"] * a.C),
             "--channel_swap", ",".join(str(i) for i in range(a.C))],
            os.path.join(d, "parse.txt"))
        print("[%s] parse rc=%d %s %s" % (kind, rc, os.path.exists(
            os.path.join(jr, "m_parsed.json")), err_of(txt)))
        rc, txt, secs = run(
            [os.path.join(BIN, "icraft-quantize.exe"),
             "--json", os.path.join(jr, "m_parsed.json"),
             "--raw", os.path.join(jr, "m_parsed.raw"), "--jr_path", d,
             "--qdtype", "int8", "--target", "zhuge",
             "--forward_dir", cal, "--forward_list", lst,
             "--saturation", "kld", "--per", "tensor", "--no_transinput", "true",
             "--log_path", os.path.join(d, "qlog")],
            os.path.join(d, "quantize.txt"))
        qj = os.path.join(d, "m_quantized.json")
        print("      quant(int8) rc=%d %s %s" % (rc, os.path.exists(qj), err_of(txt)))
        if not os.path.exists(qj):
            continue
        rd = os.path.join(d, "run")
        os.makedirs(rd, exist_ok=True)
        rc, txt, secs = run(
            [os.path.join(BIN, "icraft-run.exe"), "--json", qj,
             "--raw", os.path.join(d, "m_quantized.raw"), "--input", inp,
             "--backends", "Host", "--log_path", os.path.join(rd, "logs"),
             "--dump_format", "SFB", "--dump_ftmp", "2"],
            os.path.join(d, "run.txt"))
        dumps = []
        for root, _dd, fs in os.walk(os.path.join(rd, "logs")):
            dumps += [os.path.join(root, f) for f in fs if f.endswith(".ftmp")]
        print("      run(Host)   rc=%d %5.1fs dumps=%d  %s"
              % (rc, secs, len(dumps), err_of(txt)))
        for p in dumps:
            arr = np.fromfile(p, dtype=np.float32)
            n_nan = int(np.isnan(arr).sum())
            print("        %-8s n=%d nan=%d max=%.4g" % (
                os.path.basename(p), arr.size, n_nan,
                float(np.nanmax(np.abs(arr))) if arr.size and n_nan < arr.size else float("nan")))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
