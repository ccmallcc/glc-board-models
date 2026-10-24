#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""两份名单：
 ① 【需提升】板端正本在仓库里**只**存在于 快照目录 ⇒ 快照被迫当活文档用，必须提升到主题目录。
 ② 【改名】板端文件的同名仓库副本全是旧的，但**另一个不同名**的仓库副本内容相同。
"""
import os
import hashlib
import collections

REPO = r"E:\fudanwei\GLC-共享包"
BOARD = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "证据", "board_md5.txt")
SNAP = "工具/板端脚本快照_20261015/"
SKIP = {'.git', '__pycache__', 'node_modules'}
EXT = {'.py', '.sh'}


def md5f(p):
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


board = {}
for line in open(BOARD, encoding='utf-8', errors='replace'):
    p = line.split()
    if len(p) == 2:
        board[p[1]] = p[0]

by_md5 = collections.defaultdict(list)   # md5 -> [rel]
by_name = collections.defaultdict(list)  # basename -> [(rel, md5)]
for dp, dn, fn in os.walk(REPO):
    dn[:] = [d for d in dn if d not in SKIP]
    for f in fn:
        if os.path.splitext(f)[1].lower() not in EXT:
            continue
        rel = os.path.relpath(os.path.join(dp, f), REPO).replace('\\', '/')
        try:
            m = md5f(os.path.join(dp, f))
        except OSError:
            continue
        by_md5[m].append(rel)
        by_name[f].append((rel, m))

print("== ① 正本只在快照里（需提升到主题目录）==")
n = 0
for bpath, m in sorted(board.items()):
    if '/_ui_backup' in bpath or '/udmabuf' in bpath:
        continue
    copies = by_md5.get(m, [])
    if copies and all(c.startswith(SNAP) for c in copies):
        n += 1
        print("   %s  %-30s" % (m[:8], bpath))
        for c in copies:
            print("        ← %s" % c)
        print("        （仓库里的同名旧版：%s）" % ", ".join(
            "%s=%s" % (r, mm[:8]) for r, mm in by_name[os.path.basename(bpath)] if mm != m) or "无")
print("   小计 %d 个\n" % n)

print("== ② 板端文件在仓库里【改名】存放 ==")
n = 0
for bpath, m in sorted(board.items()):
    if '/_ui_backup' in bpath or '/udmabuf' in bpath:
        continue
    name = os.path.basename(bpath)
    same = [r for r, mm in by_name.get(name, []) if mm == m]
    if same:
        continue                      # 同名副本已经对得上，不算改名
    others = [c for c in by_md5.get(m, []) if os.path.basename(c) != name]
    if others:
        n += 1
        print("   板上 %s" % bpath)
        for c in others:
            print("        == %s" % c)
print("   小计 %d 个\n" % n)
