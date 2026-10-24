# -*- coding: utf-8 -*-
r"""adapt A/B：ZhugePadLayoutPass 关掉后，Transpose/Reshape 会掉多少？

背景（逐阶段实测，E:\fudanwei\工作区\compile2\s4_int8）：
    parsed    671 op   Transpose 188   Reshape 172
    optimized 659 op   Transpose 250   Reshape 102
    quantized 667 op   Transpose 250   Reshape 102
    adapted  1844 op   Transpose 494   Reshape 660     ← 这一跳暴涨
    ZG       1116 op   Transpose 494   Reshape 315

Icraft-3.36.1\bin\zhuge\adapter.toml:
    essential_passes = ["icraft.AddCopy2noInsOpPass"]
    common_passes    = [..., "icraft.ZhugePadLayoutPass", ...]
⇒ ZhugePadLayoutPass 在 common(可选) 里，用 --pass_off 应该能关。

用法：python adapt_ab.py [--only A|B|C|D]
"""
import argparse
import collections
import json
import os
import subprocess
import sys
import time

BIN = r"E:\fudanwei\Icraft-3.36.1\bin"
SRC = r"E:\fudanwei\工作区\compile2\s4_int8\s4_gs_generator_quantized"
OUT = r"E:\fudanwei\_exp_adapt"

CASES = [
    ("A_baseline", []),
    ("B_noPad",    ["--pass_off", "icraft.ZhugePadLayoutPass"]),
    ("C_noPad2",   ["--pass_off", "ZhugePadLayoutPass"]),
    ("D_noPad_noConv", ["--pass_off", "icraft.ZhugePadLayoutPass",
                        "--pass_off", "icraft.ConvertTranspose2ReshapePass"]),
]


def count(path):
    d = json.load(open(path, encoding="utf-8"))
    ops = d.get("ops", [])
    c = collections.Counter()
    for o in ops:
        tk = str(o.get("_type_key", "?")).split("::")[-1]
        c[tk] += 1
    return len(ops), c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    print("源 = %s.json  (%.1f MB)" % (SRC, os.path.getsize(SRC + ".json") / 1e6))
    print("%-16s %7s %8s %10s %8s   %s" % ("case", "耗时s", "算子数", "Transpose", "Reshape", "输出"))
    print("-" * 92)

    for tag, extra in CASES:
        if a.only and not tag.startswith(a.only):
            continue
        od = os.path.join(OUT, tag)
        os.makedirs(od, exist_ok=True)
        cmd = [os.path.join(BIN, "icraft-adapt.exe"),
               "--json", SRC + ".json", "--raw", SRC + ".raw",
               "--jr_path", od, "--target", "zhuge",
               "--log_path", os.path.join(od, "log")] + extra
        t0 = time.time()
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=7200)
        el = time.time() - t0
        txt = p.stdout.decode("utf-8", "replace")
        open(os.path.join(od, "adapt.txt"), "w", encoding="utf-8", errors="replace").write(
            "CMD: " + " ".join(cmd) + "\n\n" + txt)
        js = [f for f in os.listdir(od) if f.endswith(".json")]
        if p.returncode != 0 or not js:
            # 抓最后几行有信息量的
            tail = [l.strip() for l in txt.replace("\r", "\n").split("\n")
                    if l.strip() and "GetConsoleMode" not in l and "SetConsoleMode" not in l]
            print("%-16s %7.0f %8s %10s %8s   rc=%d %s"
                  % (tag, el, "-", "-", "-", p.returncode, " | ".join(tail[-3:])[:150]))
            continue
        # 取最大的那个 json（跳板文件可能不止一个）
        js.sort(key=lambda f: -os.path.getsize(os.path.join(od, f)))
        n, c = count(os.path.join(od, js[0]))
        print("%-16s %7.0f %8d %10d %8d   %s" % (tag, el, n, c.get("TransposeNode", 0) + c.get("Transpose", 0),
                                                 c.get("ReshapeNode", 0) + c.get("Reshape", 0), js[0]))
    print("-" * 92)


if __name__ == "__main__":
    main()
