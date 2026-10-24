#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""try_quant.py —— 三分对照，定位 icraft-quantize 为什么无声崩溃

A. 用**原来的 calibref(9 张)** + compile3 的 optimized 文件  -> 复现已知成功的情形
B. 用 calibref_real 的**前 9 张**                            -> 数量少时行不行
C. 用 calibref_real 的**全部 56 张**                         -> 完整重标定

每次都打印 Windows 退出码（负数/大数往往代表崩溃，例如 0xC0000005 = 访问违例）。
"""
import os
import shutil
import subprocess
import sys
import time

BIN = r"E:\fudanwei\Icraft-3.36.1\bin\icraft-quantize.exe"
WS = r"E:\fudanwei\工作区"
SRC = os.path.join(WS, "compile3", "s4_int8_real")
OPT_JSON = os.path.join(SRC, "s4_gs_generator_optimized.json")
OPT_RAW = os.path.join(SRC, "s4_gs_generator_optimized.raw")
CAL_REF = os.path.join(WS, "calibref", "calib", "s4_gs_generator")
CAL_REAL = os.path.join(WS, "calibref_real", "calib", "s4_gs_generator")


def run_case(tag, fwd_dir, fwd_list, outdir):
    os.makedirs(outdir, exist_ok=True)
    cmd = [BIN, "--json", OPT_JSON, "--raw", OPT_RAW,
           "--jr_path", outdir, "--qdtype", "int8", "--target", "zhuge",
           "--log_path", os.path.join(outdir, "qlog"),
           "--forward_dir", fwd_dir, "--forward_list", fwd_list,
           "--saturation", "kld", "--per", "tensor", "--no_transinput", "true"]
    print("=" * 74)
    print("### %s" % tag)
    print("   forward_dir  = %s" % fwd_dir)
    print("   forward_list = %s" % fwd_list)
    with open(fwd_list, encoding='utf-8', errors='replace') as f:
        n = len([l for l in f if l.strip()])
    print("   list 条数    = %d" % n)
    print("   输出 -> %s" % outdir)
    t0 = time.time()
    with open(os.path.join(outdir, "run.log"), "wb") as lf:
        p = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT)
    dt = time.time() - t0
    rc = p.returncode
    # 解释退出码
    if rc == 0:
        note = "OK"
    elif rc < 0 or rc > 0x7FFFFFFF:
        note = "崩溃? (0x%08X)" % (rc & 0xFFFFFFFF)
    else:
        note = "非零退出 %d (0x%08X)" % (rc, rc)
    outs = sorted(os.listdir(outdir))
    print("   >>> rc=%d  %s   用时 %.1f s" % (rc, note, dt))
    print("   >>> 产物: %s" % ", ".join(outs))
    big = [f for f in outs if f.endswith(('.json', '.raw')) and 'quantized' in f]
    print("   >>> %s" % ("✅ 生成了 quantized 文件" if big else "❌ 没有 quantized 产物"))
    return rc, dt


def main():
    # B 用：从 calibref_real 里取前 9 张，单独写一个 list
    s9dir = os.path.join(WS, "compile3", "_calib_real_9")
    os.makedirs(s9dir, exist_ok=True)
    names = [l.strip() for l in open(os.path.join(CAL_REAL, "list.txt")) if l.strip()]
    with open(os.path.join(s9dir, "list.txt"), "w") as f:
        for nm in names[:9]:
            f.write(nm + "\n")

    cases = [
        ("A. calibref(9 张) + compile3 的 optimized  -> 复现已知成功",
         CAL_REF, os.path.join(CAL_REF, "list.txt"),
         os.path.join(WS, "compile3", "_probeA")),
        ("B. calibref_real 前 9 张",
         CAL_REAL, os.path.join(s9dir, "list.txt"),
         os.path.join(WS, "compile3", "_probeB")),
        ("C. calibref_real 全 56 张",
         CAL_REAL, os.path.join(CAL_REAL, "list.txt"),
         os.path.join(WS, "compile3", "_probeC")),
    ]
    res = []
    for tag, d, l, o in cases:
        try:
            res.append((tag.split('.')[0],) + run_case(tag, d, l, o))
        except Exception as e:
            print("   !! 异常: %s" % e)
            res.append((tag.split('.')[0], None, 0))
    print("=" * 74)
    print("### 汇总")
    for tag, rc, dt in res:
        print("   %-4s rc=%-12s 用时 %5.1f s" % (tag, rc, dt))
    print("TRY_QUANT_DONE")


if __name__ == "__main__":
    main()
