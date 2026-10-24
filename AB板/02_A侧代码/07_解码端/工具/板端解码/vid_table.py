#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vid_table.py —— 从 _ZG.json 里把各子图真正的输入/输出 v_id 挖出来

校准依据：**s1 的 v_id 是实测能 dump 出来的**（板端 `--dump_ftmp 3310,3314` 成功过）。
所以只要看 s1 的 Output 节点 inputs 是不是 [3310,3314]，就能确定"dump 该用哪个 id"。
"""
import json
import os

BASE = r"E:\fudanwei\工作区\compile2"
JOBS = [
    ("s1",  "s1_int8",  "s1_encoder_ga_hyper_ZG.json", [3310, 3314]),
    ("s2",  "s2_int8",  "s2_hyperdec_fusion_ZG.json",  [184]),
    ("s3p1", "s3p1_int8", "s3_phase1_ZG.json",         [178, 182]),
    ("s3p2", "s3p2_int8", "s3_phase2_ZG.json",         [178, 182]),
    ("s3p3", "s3p3_int8", "s3_phase3_ZG.json",         [178, 182]),
    ("s4",  "s4_int8",  "s4_gs_generator_ZG.json",     [4115]),
]


def _id(v):
    """value 引用可能是 int，也可能是 dict（带 id 字段）—— 统一成 int"""
    if isinstance(v, int):
        return v
    if isinstance(v, dict):
        for k in ('id', 'v_id', 'value_id', 'value', 'vid'):
            if k in v and isinstance(v[k], int):
                return v[k]
        return ('DICT:' + ','.join(sorted(v.keys())))
    return v


def analyze(path):
    d = json.load(open(path, encoding='utf-8'))
    ops = d['ops']
    in_ids, out_ids = [], []
    for o in ops:
        tk = o.get('_type_key', '')
        if tk.endswith('::Input'):
            in_ids = [_id(v) for v in (o.get('outputs') or [])]
        elif tk.endswith('::Output'):
            out_ids = [_id(v) for v in (o.get('inputs') or [])]
    allv = set()
    for o in ops:
        for v in (o.get('inputs') or []):
            x = _id(v)
            if isinstance(x, int):
                allv.add(x)
        for v in (o.get('outputs') or []):
            x = _id(v)
            if isinstance(x, int):
                allv.add(x)
    return d, in_ids, out_ids, allv


def main():
    print("=" * 82)
    print("### 从 _ZG.json 挖出的输入/输出 v_id")
    print("=" * 82)
    print("  %-6s %-35s %-14s %-16s" % ("子图", "json", "Input->value", "Output<-value"))
    print("  " + "-" * 76)
    rows = {}
    for tag, sub, fn, table_ids in JOBS:
        p = os.path.join(BASE, sub, "gen", fn)
        if not os.path.exists(p):
            print("  %-6s !! 缺 %s" % (tag, p))
            continue
        d, i_ids, o_ids, allv = analyze(p)
        rows[tag] = (i_ids, o_ids, allv, table_ids)
        print("  %-6s %-35s %-14s %-16s" % (tag, fn, i_ids, o_ids))

    print("\n" + "=" * 82)
    print("### 逐个子图核对")
    print("=" * 82)
    for tag, (i_ids, o_ids, allv, table_ids) in rows.items():
        print("\n  --- %s ---" % tag)
        print("     json 里 Output 节点取的值 = %s" % o_ids)
        print("     SUB 表/文档里写的         = %s" % table_ids)
        if o_ids == table_ids:
            print("     => ✅ 完全一致"
                  + ("（注意：s1 的这组是**板端实测能 dump 出来**的，所以这就是正确用法）"
                     if tag == 's1' else ""))
        else:
            print("     => ⚠️ **不一致**")
            for v in table_ids:
                print("        表里的 %-6s 在模型里存在吗: %s" % (v, "存在" if v in allv else "❌ 不存在"))
            for v in o_ids:
                print("        实际输出值 %-6s 在模型里存在吗: %s" % (v, "存在" if v in allv else "不存在"))
        if 4115 in allv and tag == 's4':
            print("        （注：4115 **存在**于模型里，但它不是 Output 节点取的那个值）")
        elif tag == 's4':
            print("        （注：4115 **不存在**于模型的值集合里）")
        print("        模型里 value id 范围: %d ~ %d，共 %d 个"
              % (min(allv), max(allv), len(allv)))
    print("\nVID_TABLE_DONE")


if __name__ == "__main__":
    main()
