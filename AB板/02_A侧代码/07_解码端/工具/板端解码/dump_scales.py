#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dump_scales.py —— 打印 s4_int8 模型里 scale 的**原始字符串**，看清结构"""
import json
import re

P = r"E:\fudanwei\工作区\compile3\s4_int8_real40\gen\s4_gs_generator_ZG.json"
d = json.load(open(P, encoding='utf-8'))

found = []


def walk(node, path):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == 'scale':
                found.append((path, v))
            walk(v, path + '/' + str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            walk(v, path + '[%d]' % i)


walk(d, '')
print("共找到 %d 处 scale" % len(found))
print("=" * 90)
print("### 前 6 处原始字符串")
for p, v in found[:6]:
    print("  路径: %s" % p[-70:])
    print("  值  : %s" % (str(v)[:400]))
    print()
print("=" * 90)
print("### 统计：从原始字符串里抽数值，按大小排序")


def nums_of(v):
    if isinstance(v, (int, float)):
        return [float(v)]
    if not isinstance(v, str):
        return []
    # 只取 "数字" 形式的（含小数/科学计数），排除 axis 索引那种纯整数键名里的
    out = []
    for m in re.finditer(r'(?<![A-Za-z0-9_])(-?\d+\.\d+(?:[eE][-+]?\d+)?|-?\d+\.\d+)(?![0-9])', v):
        try:
            out.append(float(m.group(1)))
        except ValueError:
            pass
    return out


rows = []
for p, v in found:
    ns = nums_of(v)
    if ns:
        rows.append((max(ns), min(ns), len(ns), str(v)[:110]))
rows.sort(key=lambda r: -r[0])
print("  抽取到 %d 处含小数的 scale；按最大值降序前 15：" % len(rows))
print("  %-14s %-14s %-6s %s" % ("max", "min", "个数", "原文(截断)"))
for mx, mn, n, s in rows[:15]:
    print("  %-14.6g %-14.6g %-6d %s" % (mx, mn, n, s))
print("  ...")
for mx, mn, n, s in rows[-5:]:
    print("  %-14.6g %-14.6g %-6d %s" % (mx, mn, n, s))

# 用 max 值当对称量化 scale，看动态范围
if rows:
    top = rows[0][0]
    print("\n### 若最大 scale=%.6g 是对称 int8 的 scale，则动态范围 ≈ ±%.1f" % (top, top * 127))
    over = [r for r in rows if r[0] * 127 > 65504]
    print("### scale*127 > 65504（即超出 fp16 上限）的张量数 = %d" % len(over))
    big = [r for r in rows if r[0] * 127 > 1000]
    print("### scale*127 > 1000 的张量数 = %d" % len(big))
    if big:
        print("    （这些张量的 int8 量化台阶 ≥ %.1f）" % (big[-1][0]))
print("DUMP_SCALES_DONE")
