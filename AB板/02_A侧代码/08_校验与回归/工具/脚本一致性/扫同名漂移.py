#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描仓库里"同名但内容不同"的文件组 —— 用来找脚本漂移的口子。

判据说明（重要）：
  只按 **basename** 分组，且只报告 **md5 有分歧** 的组。
  md5 全同的同名组只报个数（那些是正常的多处副本，无风险）。
"""
import os
import sys
import hashlib
import collections

ROOT = sys.argv[1] if len(sys.argv) > 1 else r"E:\fudanwei\GLC-共享包"
SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.idea', '.vscode'}
# 只关心这些后缀（脚本/源码/配置）；md/图片的"同名"意义不大
EXT = {'.sh', '.py', '.ps1', '.c', '.h', '.cpp', '.sv', '.v', '.vhd',
       '.tcl', '.xdc', '.toml', '.json', '.cfg', '.conf', '.txt', '.bat', '.cmake'}


def md5_of(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    by_name = collections.defaultdict(list)
    for dp, dn, fn in os.walk(ROOT):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for f in fn:
            if os.path.splitext(f)[1].lower() not in EXT:
                continue
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, ROOT).replace('\\', '/')
            try:
                by_name[f].append((rel, md5_of(p)[:8], os.path.getsize(p)))
            except OSError:
                pass

    multi = {k: v for k, v in by_name.items() if len(v) > 1}
    drift = {k: v for k, v in multi.items() if len({x[1] for x in v}) > 1}

    print("== 汇总 ==")
    print("  出现在多处的文件名        : %d" % len(multi))
    print("    其中 md5 全同（安全副本）: %d" % (len(multi) - len(drift)))
    print("    其中 md5 有分歧（漂移）  : %d" % len(drift))
    print()
    for k in sorted(drift):
        v = drift[k]
        kinds = len({x[1] for x in v})
        print("-- %s  (%d 份 / %d 种)" % (k, len(v), kinds))
        for rel, m, sz in sorted(v, key=lambda x: -x[2]):
            print("     %s %8d  %s" % (m, sz, rel))
        print()


if __name__ == '__main__':
    main()
