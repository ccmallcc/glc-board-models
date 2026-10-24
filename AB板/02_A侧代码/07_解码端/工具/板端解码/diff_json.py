#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查三份 s4 json 为什么大小/md5 都不同：是不是嵌了机器相关的路径/字符串"""
import json
import os
import re

FILES = [
    ("我们的 compile2（8张 calibref）", r"E:\fudanwei\工作区\compile2\s4_int8\gen\s4_gs_generator_ZG.json"),
    ("我们的 compile3（40张真实）",     r"E:\fudanwei\工作区\compile3\s4_int8_real40\gen\s4_gs_generator_ZG.json"),
    ("B 板端那 份（1,659,119 B）",       None),
]

PATH_RE = re.compile(rb'[A-Za-z]:\\\\|[A-Za-z]:\\|/[A-Za-z]+/[A-Za-z]+/|\\\\\\\\')


def scan(tag, p):
    print("=" * 78)
    print("### %s" % tag)
    if p is None or not os.path.exists(p):
        print("   （没有本地文件，跳过）")
        return
    b = open(p, 'rb').read()
    print("   大小 = %d B" % len(b))
    d = json.loads(b.decode('utf-8'))
    # 1) 顶层有没有路径类字段
    print("   顶层键: %s" % list(d.keys()))
    print("   tags   = %s" % d.get('tags'))
    print("   params_bytes=%s  params_md5=%s" % (d.get('params_bytes'), d.get('params_md5')))
    print("   icraft_version=%s  icraft_xir_version=%s  ai_target=%s"
          % (d.get('icraft_version'), d.get('icraft_xir_version'), d.get('ai_target')))
    # 2) 全文找 Windows/Unix 路径样子的字符串
    hits = set()
    for m in re.finditer(rb'"([^"]{0,200})"', b):
        s = m.group(1)
        if b':' in s and (b'\\' in s or b'/' in s) and len(s) > 4:
            hits.add(s[:160])
    print("   疑似路径/含冒号的字符串（%d 条，最多列 12）:" % len(hits))
    for h in list(hits)[:12]:
        try:
            print("      %s" % h.decode('utf-8', 'replace'))
        except Exception:
            print("      %r" % h)
    # 3) ops 里的 name 有没有带路径
    names = set()
    for o in d['ops']:
        nm = o.get('name')
        if isinstance(nm, str) and ('\\' in nm or '/' in nm or ':' in nm):
            names.add(nm[:120])
    print("   op.name 里含路径样式的（%d 条，最多列 8）:" % len(names))
    for n in list(names)[:8]:
        print("      %s" % n)


def diff_two(p1, p2):
    print("=" * 78)
    print("### 我们两份的结构差异（compile2 vs compile3）")
    d1 = json.load(open(p1, encoding='utf-8'))
    d2 = json.load(open(p2, encoding='utf-8'))
    for k in sorted(set(d1) | set(d2)):
        a, b = d1.get(k), d2.get(k)
        if k == 'ops':
            print("   ops: 各 %d / %d 个" % (len(a), len(b)))
            # 逐 op 比，统计有多少个不同
            nd = 0
            for i, (x, y) in enumerate(zip(a, b)):
                if json.dumps(x, sort_keys=True) != json.dumps(y, sort_keys=True):
                    nd += 1
            print("        其中内容不同的 op = %d 个" % nd)
            # 找一个不同的 op 看看差在哪
            for i, (x, y) in enumerate(zip(a, b)):
                if json.dumps(x, sort_keys=True) != json.dumps(y, sort_keys=True):
                    print("        第一个不同的 op[%d]:" % i)
                    print("           old = %s" % json.dumps(x, ensure_ascii=False)[:300])
                    print("           new = %s" % json.dumps(y, ensure_ascii=False)[:300])
                    break
        elif a != b:
            print("   %-22s 不同: %r  vs  %r" % (k, a, b))
        else:
            print("   %-22s 相同: %r" % (k, a))


if __name__ == "__main__":
    for tag, p in FILES:
        scan(tag, p)
    diff_two(FILES[0][1], FILES[1][1])
    print("=" * 78)
    print("DIFF_JSON_DONE")
