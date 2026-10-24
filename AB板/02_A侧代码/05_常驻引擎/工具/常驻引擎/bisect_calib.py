#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bisect_calib.py —— 二分找出 icraft-quantize.exe 最多能吃多少张标定样本

已知：8 张 OK、9 张 OK、56 张 0xC0000005 崩溃。
逐个试 16 / 24 / 32 / 40 / 48，找出能跑通的最大档。
"""
import os
import subprocess
import sys
import time

BIN = r"E:\fudanwei\Icraft-3.36.1\bin\icraft-quantize.exe"
WS = r"E:\fudanwei\工作区"
SRC = os.path.join(WS, "compile3", "s4_int8_real")
OPT_JSON = os.path.join(SRC, "s4_gs_generator_optimized.json")
OPT_RAW = os.path.join(SRC, "s4_gs_generator_optimized.raw")
CAL_REAL = os.path.join(WS, "calibref_real", "calib", "s4_gs_generator")
SUB = os.path.join(WS, "compile3", "_calib_sub")


def make_list(n):
    os.makedirs(SUB, exist_ok=True)
    names = [l.strip() for l in open(os.path.join(CAL_REAL, "list.txt")) if l.strip()]
    p = os.path.join(SUB, "list_%d.txt" % n)
    with open(p, "w") as f:
        for nm in names[:n]:
            f.write(nm + "\n")
    return p


def try_n(n):
    out = os.path.join(WS, "compile3", "_probeN%d" % n)
    os.makedirs(out, exist_ok=True)
    lp = make_list(n)
    cmd = [BIN, "--json", OPT_JSON, "--raw", OPT_RAW,
           "--jr_path", out, "--qdtype", "int8", "--target", "zhuge",
           "--log_path", os.path.join(out, "qlog"),
           "--forward_dir", CAL_REAL, "--forward_list", lp,
           "--saturation", "kld", "--per", "tensor", "--no_transinput", "true"]
    t0 = time.time()
    with open(os.path.join(out, "run.log"), "wb") as lf:
        p = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT)
    dt = time.time() - t0
    ok = any('quantized' in f for f in os.listdir(out))
    rc = p.returncode
    print("   N=%-3d  rc=%-12s %-12s 用时 %5.1f s  %s"
          % (n, rc, ("0x%08X" % (rc & 0xFFFFFFFF)) if rc else "OK",
             dt, "有产物" if ok else "无产物"), flush=True)
    return ok, rc, dt


def main():
    print("=== 二分：icraft-quantize 能吃多少张标定样本 ===", flush=True)
    print("   已知： 8 张 OK / 9 张 OK / 56 张 崩溃(0xC0000005)", flush=True)
    results = {}
    for n in (16, 24, 32, 40, 48):
        ok, rc, dt = try_n(n)
        results[n] = (ok, rc, dt)
        if not ok:
            print("   -> N=%d 起崩，后面不用试了" % n, flush=True)
            break
    print("=" * 66)
    print("### 汇总")
    for n, (ok, rc, dt) in results.items():
        print("   N=%-3d  %s  rc=%s" % (n, "✅ 可用" if ok else "❌ 崩溃", rc))
    good = [n for n, v in results.items() if v[0]]
    print("### 能跑通的最大档 = %s" % (max(good) if good else "（连 16 都不行）"))
    print("BISECT_DONE")


if __name__ == "__main__":
    main()
