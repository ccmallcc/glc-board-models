#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""yh_stats_calib.py —— 统计三套标定集（s4_gs_generator 的输入 = y_hat）的分布

s4 的输入 y_hat 形状 (1,256,16,16) fp32 = 262144 B，标定样本正好是这个大小。
⇒ 直接读出来统计，就知道 **int8 模型是在什么分布上标定的**。
"""
import os
import sys

import numpy as np

BASE = r"E:\fudanwei\工作区"
SETS = [("calibref", 9), ("calibref_kodak", 9), ("calibref_real", 57)]


def stats(a):
    a = a.reshape(-1)
    qs = [0.1, 1, 5, 25, 50, 75, 95, 99, 99.9]
    pct = np.percentile(a, qs)
    return dict(n=a.size, mn=float(a.min()), mx=float(a.max()),
                mean=float(a.mean()), std=float(a.std()),
                absmax=float(np.abs(a).max()),
                pct=dict(zip(qs, [float(v) for v in pct])))


def main():
    allrows = {}
    for name, expect in SETS:
        d = os.path.join(BASE, name, "calib", "s4_gs_generator")
        if not os.path.isdir(d):
            print("!! 缺目录 %s" % d)
            continue
        files = sorted(f for f in os.listdir(d) if f.endswith('.ftmp'))
        print("=" * 78)
        print("### %-16s  %d 个样本" % (name, len(files)))
        per = []
        cat = []
        for f in files:
            a = np.fromfile(os.path.join(d, f), dtype=np.float32)
            if a.size != 256 * 16 * 16:
                print("   !! %s 大小异常 %d" % (f, a.size))
                continue
            per.append((f, stats(a)))
            cat.append(a)
        if not per:
            continue
        big = np.concatenate(cat)
        s = stats(big)
        print("   【合并统计】min=%.4f  max=%.4f  |max|=%.4f  mean=%.4f  std=%.4f"
              % (s['mn'], s['mx'], s['absmax'], s['mean'], s['std']))
        print("   分位数: " + "  ".join("%g%%=%.3f" % (k, v) for k, v in s['pct'].items()))
        # 每样本的 min/max 极值范围
        mins = [p[1]['mn'] for p in per]
        maxs = [p[1]['mx'] for p in per]
        abss = [p[1]['absmax'] for p in per]
        print("   各样本 min 范围 [%.3f, %.3f] ；max 范围 [%.3f, %.3f] ；|x|max 最大 %.3f"
              % (min(mins), max(mins), min(maxs), max(maxs), max(abss)))
        # 落在常见 int8 激活范围外的比例
        for lo, hi in ((-8, 8), (-16, 16), (-32, 32)):
            out = float(((big < lo) | (big > hi)).mean()) * 100
            print("   落在 [%d, %d] 之外的比例：**%.4f%%**" % (lo, hi, out))
        allrows[name] = s
    print("=" * 78)
    print("### 三套对比（|x| 最大值 / 99.9 分位 / 超 ±8 比例）")
    print("   %-18s %10s %10s %10s" % ("标定集", "|x|max", "99.9%", ">|8|"))
    for name, _ in SETS:
        if name in allrows:
            s = allrows[name]
            big = None
            d = os.path.join(BASE, name, "calib", "s4_gs_generator")
            cat = [np.fromfile(os.path.join(d, f), dtype=np.float32)
                   for f in sorted(os.listdir(d)) if f.endswith('.ftmp')]
            big = np.concatenate(cat)
            out8 = float(((big < -8) | (big > 8)).mean()) * 100
            print("   %-18s %10.4f %10.4f %9.4f%%"
                  % (name, s['absmax'], s['pct'][99.9], out8))
    print("CALIB_STATS_DONE")


if __name__ == "__main__":
    main()
