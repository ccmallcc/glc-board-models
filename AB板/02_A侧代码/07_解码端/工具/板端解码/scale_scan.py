#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scale_scan.py —— 从 _ZG.json 里把**每个张量的量化 scale**挖出来，看动态范围

动机：
  实测 int8 单图（A 板，新模型）p1 = **18.81 dB**，而同一个容器 s4_split5 = **41.71 dB**
  —— 差 23 dB。这不是"int8 粗一点"能解释的。
  猜想：S4 生成器内部数值**逐段放大 ~10^4 倍**（B 侧实测 s4b3 到 -45696/58816/inf），
        而 int8 是 **per-tensor** 一个 scale ⇒ 一个 range ±58816 但典型值 ~1 的张量，
        量化台阶 = 58816/128 ≈ 460 ⇒ **精度全丢**。
  验证：直接从模型 json 里读 scale，看有没有 range 极大的张量。
"""
import json
import os
import re

MODELS = [
    ("新（40 张真实）", r"E:\fudanwei\工作区\compile3\s4_int8_real40\gen\s4_gs_generator_ZG.json"),
]
BASE = r"E:\fudanwei\工作区\compile2"
for t in ("s4_int8", "s4_bf16", "s4_tf32"):
    p = os.path.join(BASE, t, "gen", "s4_gs_generator_ZG.json")
    if os.path.exists(p):
        MODELS.append(("对照 %s" % t, p))

NUM = re.compile(r'-?\d+\.?\d*(?:e[-+]?\d+)?')


def scan(tag, path):
    print("=" * 82)
    print("### %s" % tag)
    print("    %s" % path)
    d = json.load(open(path, encoding='utf-8'))
    dims = d.get('dtype') or {}
    # 递归找所有 QuantizedType
    rows = []

    def walk(node, where):
        if isinstance(node, dict):
            tk = node.get('_type_key', '')
            if tk.endswith('QuantizedType') or 'scale' in node:
                sc = node.get('scale')
                if isinstance(sc, str):
                    nums = [float(x) for x in NUM.findall(sc)]
                    if nums:
                        mx = max(abs(x) for x in nums)
                        rows.append((where, len(nums), mx, sc[:90]))
                elif isinstance(sc, (int, float)):
                    rows.append((where, 1, abs(float(sc)), str(sc)))
            for k, v in node.items():
                walk(v, where + '/' + str(k) if where else str(k))
        elif isinstance(node, list):
            for i, v in enumerate(node[:400]):
                walk(v, where)

    walk(d, '')
    # 只保留看起来像量化的（有 scale 的）
    if not rows:
        print("    没找到 QuantizedType/scale")
        return
    # 按 scale 最大值排序
    rows.sort(key=lambda r: -r[2])
    print("    找到 %d 处带 scale 的地方；按 scale 降序取前 12：" % len(rows))
    print("      %-14s %-8s %-12s %s" % ("scale值", "个数", "≈动态范围", "位置(截断)"))
    for where, n, mx, sample in rows[:12]:
        # int8 对称量化：range ≈ scale * 127
        rng = mx * 127
        print("      %-14.6g %-8d %-12.1f %s" % (mx, n, rng, where[-58:]))
    print("      ...")
    for where, n, mx, sample in rows[-4:]:
        print("      %-14.6g %-8d %-12.1f %s" % (mx, n, mx * 127, where[-58:]))


if __name__ == "__main__":
    for tag, p in MODELS:
        if os.path.exists(p):
            scan(tag, p)
        else:
            print("!! 缺 %s" % p)
    print("=" * 82)
    print("SCALE_SCAN_DONE")
