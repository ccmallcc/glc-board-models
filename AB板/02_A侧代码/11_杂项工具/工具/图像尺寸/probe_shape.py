#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""判定：s4 生成器能不能换成别的输入尺寸（比如 32x32 latent -> 512x512 图）。

做法：拿同一个 ONNX，用两个不同的 --inputs 各跑一遍 icraft-parse，
      然后看**图里的空间尺寸/序列长度有没有跟着变**。
      · 如果 4096 变成 16384  => reshape 是动态的，**重编译就能换尺寸** ✓
      · 如果还是 4096         => 写死的，**必须重新导出 ONNX** ✗
"""
import json
import os
import subprocess
import sys

BIN = r"E:\fudanwei\Icraft-3.36.1\bin"
SRC = r"E:\fudanwei\工作区\onnx\c1_simple\s4_gs_generator.onnx"
OUTROOT = r"E:\fudanwei\工作区\parse_test"
C = 256   # s4 的输入通道数


def run(shape):
    tag = shape.replace(",", "_")
    out = os.path.join(OUTROOT, tag)
    os.makedirs(out, exist_ok=True)
    cmd = [os.path.join(BIN, "icraft-parse.exe"),
           "--net_name", "s4_gs_generator", "--network", SRC, "--jr_path", out,
           "--log_path", os.path.join(out, "plog"),
           "--framework", "ONNX", "--frame_version", "opset17", "--target", "zhuge",
           "--inputs_dtype", "FP32", "--inputs", shape, "--inputs_layout", "NHWC",
           "--pre_method", "nop",
           "--pre_scale", ",".join(["1.0"] * C),
           "--pre_mean", ",".join(["0.0"] * C),
           "--channel_swap", ",".join(str(i) for i in range(C))]
    p = subprocess.run(cmd, capture_output=True)
    txt = p.stdout.decode("utf-8", "replace")
    pj = os.path.join(out, "s4_gs_generator_parsed.json")
    ok = os.path.exists(pj)
    print("  inputs=%-14s rc=%d  parsed=%s" % (shape, p.returncode, "是" if ok else "否"))
    if not ok:
        for ln in txt.strip().splitlines()[-6:]:
            print("      " + ln)
        return None
    return pj


def probe(pj, tag):
    j = json.load(open(pj, encoding="utf-8"))
    ops = j["ops"]
    shapes = []
    for o in ops:
        for v in (o.get("outputs") or []):
            d = v.get("dtype")
            sh = d.get("shape") if isinstance(d, dict) else None
            if sh:
                shapes.append(tuple(sh))
    seqs = sorted({s[-1] for s in shapes if len(s) == 3})
    big3d = sorted({s for s in shapes if len(s) == 3})
    print("  [%s] 算子数=%d" % (tag, len(ops)))
    print("        输入 %s  ->  输出 %s" % (ops[0]["outputs"][0]["dtype"]["shape"],
                                          ops[-2]["outputs"][0]["dtype"]["shape"]))
    print("        图里出现的 3维形状: %s" % (big3d[:6],))
    print("        末尾维（attention 序列长度）候选: %s" % (seqs[-6:],))
    return set(seqs)


print("=" * 78)
print("A) 原尺寸 1,16,16,256")
pa = run("1,16,16,256")
print()
print("B) 放大一倍 1,32,32,256")
pb = run("1,32,32,256")

if pa and pb:
    print()
    print("=" * 78)
    print("对照")
    sa = probe(pa, "16x16")
    sb = probe(pb, "32x32")
    print()
    if sa != sb:
        print("  ==> 序列长度**跟着变了**  => reshape 是动态的，**重编译就能换尺寸** ✓")
    else:
        print("  ==> 序列长度**没变**      => 尺寸是写死的，**必须重新导出 ONNX** ✗")
elif pa and not pb:
    print()
    print("  ==> 32x32 根本 parse 不过 => **必须重新导出 ONNX** ✗")
print("DONE")
