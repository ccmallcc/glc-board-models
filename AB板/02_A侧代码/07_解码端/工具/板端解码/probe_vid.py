#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""找 _ZG.json 里的输入/输出 v_id（对比新旧两份）"""
import json
import sys

NEW = r"E:\fudanwei\工作区\compile3\s4_int8_real40\gen\s4_gs_generator_ZG.json"
OLD = r"E:\fudanwei\工作区\compile2\s4_int8\gen\s4_gs_generator_ZG.json"


def probe(path, tag):
    print("=" * 74)
    print("### %s   %s" % (tag, path))
    d = json.load(open(path, encoding='utf-8'))
    ops = d['ops']
    print("  name=%s  ops=%d  icraft_version=%s  ai_target=%s"
          % (d.get('name'), len(ops), d.get('icraft_version'), d.get('ai_target')))
    print("  params_bytes=%s  params_md5=%s" % (d.get('params_bytes'), d.get('params_md5')))
    print("  tags=%s" % d.get('tags'))

    # 一个 op 长什么样
    print("\n  --- 第 0 个 op 的键 ---")
    o0 = ops[0]
    print("   ", list(o0.keys()))
    print("    _type_key =", o0.get('_type_key'))

    # 统计 op 类型
    from collections import Counter
    tc = Counter(o.get('_type_key') for o in ops)
    print("\n  --- op 类型分布 ---")
    for k, v in tc.most_common(8):
        print("    %-40s %d" % (k, v))

    # 找 Input / Output 类的 op，打印其所有 value id
    print("\n  --- 含 Input/Output 的 op ---")
    for i, o in enumerate(ops):
        tk = o.get('_type_key', '')
        if 'Input' in tk or 'Output' in tk:
            print("    op[%d] %s" % (i, tk))
            for key in ('inputs', 'outputs'):
                vals = o.get(key)
                if isinstance(vals, list):
                    ids = []
                    for v in vals:
                        if isinstance(v, dict):
                            ids.append(v.get('id', v.get('v_id', v.get('value_id', '?'))))
                        else:
                            ids.append(v)
                    print("       %-8s -> %s" % (key, ids))
                else:
                    print("       %-8s -> %s" % (key, vals))

    # 顶层有没有 outputs 字段
    for key in ('inputs', 'outputs', 'input_ids', 'output_ids'):
        if key in d:
            print("\n  顶层 %s = %s" % (key, d[key]))

    # 所有 value id 的集合（若 op 里有 output id）
    return d


if __name__ == '__main__':
    probe(OLD, "旧（8 张 calibref）")
    probe(NEW, "新（40 张真实照片）")
    print("=" * 74)
    print("PROBE_VID_DONE")
