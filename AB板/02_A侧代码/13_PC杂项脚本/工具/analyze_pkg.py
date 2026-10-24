#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_pkg.py —— 分析 Xilinx 官方封装管脚文件 xc7z030ffg676pkg.txt

来源（公开，HTTP 200）：
  https://download.amd.com/adaptive-socs-and-fpgas/developer/adaptive-socs-and-fpgas/package-pinout-files/z7packages/xc7z030ffg676pkg.txt
  原始入口 https://www.xilinx.com/support/packagefiles/z7packages/xc7z030ffg676pkg.txt （301 跳转）

这是 `jfmql30tai` 在 Vivado 里对应的器件（`xc7z030ffg676-2`，见《复微JFMQL30TAI器件VIVADO开发流程》§2.1）。
它能回答「某个管脚**在器件里**是什么」，但**不能**回答「板上接到了什么」——那要原理图。

输出：把结论打印出来，并生成 clock_capable.txt（所有可作 PL 时钟输入的脚）。
"""
import re
import sys
import os

SRC = sys.argv[1] if len(sys.argv) > 1 else "/mnt/e/fudanwei/_logs/pdf/xc7z030ffg676pkg.txt"
OUT = sys.argv[2] if len(sys.argv) > 2 else "/mnt/e/fudanwei/_logs/pdf/clock_capable.txt"

rows = []
for line in open(SRC, encoding="utf-8", errors="replace"):
    if line.startswith("Device/Package") or line.strip().startswith("Pin "):
        continue
    p = line.split()
    if len(p) < 7:
        continue
    pin, name = p[0], p[1]
    # 列：Pin Name MemoryByteGroup Bank VCCAUXGroup SuperLogicRegion IOType NoConnect
    bank, iotype = p[3], p[7] if len(p) > 7 else p[6]
    rows.append((pin, name, bank, iotype, line.rstrip()))

print("=" * 78)
print("xc7z030ffg676 管脚文件分析（来源：Xilinx/AMD 官方 package pinout file）")
print("=" * 78)
print("总行数 : %d" % len(rows))

types = {}
for r in rows:
    types[r[3]] = types.get(r[3], 0) + 1
print("\n--- I/O Type 分布 ---")
for k in sorted(types, key=lambda x: -types[x]):
    print("  %-12s %4d" % (k, types[k]))

# 时钟专用脚：名字里带 MRCC / SRCC
mrcc = [r for r in rows if "_MRCC_" in r[1]]
srcc = [r for r in rows if "_SRCC_" in r[1]]
gtx = [r for r in rows if r[3] == "GTX"]
print("\n--- 时钟相关脚 ---")
print("  MRCC（多区域时钟脚）: %d" % len(mrcc))
print("  SRCC（单区域时钟脚）: %d" % len(srcc))
print("  GTX （GT 参考时钟等）: %d" % len(gtx))

# 按 bank 汇总 MRCC/SRCC —— 这些才可能当 PL 时钟输入
print("\n--- 可按 Bank 当 PL 时钟输入的脚（MRCC/SRCC），只列 PL 侧 bank(>=34) ---")
bybank = {}
for r in mrcc + srcc:
    m = re.search(r"_(\d+)$", r[1])
    if not m:
        continue
    b = int(m.group(1))
    if b < 34:
        continue
    bybank.setdefault(b, []).append(r)

n = 0
for b in sorted(bybank):
    lst = sorted(bybank[b], key=lambda r: r[0])
    print("  Bank %-3d : %s" % (b, "  ".join("%s=%s" % (r[0], r[1]) for r in lst)))
    n += len(lst)
print("  合计 %d 个候选脚（这些是'能当时钟'的脚；**板子接没接由原理图决定**）" % n)

# 特别确认 R5/R6
print("\n--- 本次要查的 R5 / R6 ---")
for r in rows:
    if r[0] in ("R5", "R6"):
        print("  %s" % r[4].rstrip())

with open(OUT, "w") as f:
    f.write("# xc7z030ffg676 所有可作时钟输入的脚（MRCC/SRCC），来源：Xilinx 官方 package pinout file\n")
    f.write("# 格式: pin  pin_name  bank\n")
    for r in sorted(mrcc + srcc, key=lambda r: r[0]):
        f.write("%-5s %-32s %s\n" % (r[0], r[1], r[2]))
print("\n已写出 %s（%d 行）" % (OUT, len(mrcc) + len(srcc)))
