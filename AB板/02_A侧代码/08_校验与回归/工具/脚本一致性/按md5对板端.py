#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把仓库里的脚本与"板上实际在跑的"按 md5 对上号。

判据说明（关键）：
  **按 md5 匹配，不按文件名**。因为板端文件名可能与仓库不同
  （实例：板上的 /root/radio_check.py 实际等于仓库的 radio_check2.py）。
  只按名字比会得出错误结论。
"""
import os
import sys
import hashlib
import collections

REPO = r"E:\fudanwei\GLC-共享包"
BOARD = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "证据", "board_md5.txt")
SKIP = {'.git', '__pycache__', 'node_modules'}
EXT = {'.py', '.sh'}


def md5f(p):
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


# --- 读板端 ---
board = {}          # path -> md5
for line in open(BOARD, encoding='utf-8', errors='replace'):
    parts = line.split()
    if len(parts) == 2:
        board[parts[1]] = parts[0]

# --- 扫仓库 ---
repo_by_name = collections.defaultdict(list)   # basename -> [(rel, md5, size)]
for dp, dn, fn in os.walk(REPO):
    dn[:] = [d for d in dn if d not in SKIP]
    for f in fn:
        if os.path.splitext(f)[1].lower() not in EXT:
            continue
        p = os.path.join(dp, f)
        rel = os.path.relpath(p, REPO).replace('\\', '/')
        try:
            repo_by_name[f].append((rel, md5f(p), os.path.getsize(p)))
        except OSError:
            pass

repo_md5 = {m: r for v in repo_by_name.values() for r, m, s in v}

# --- 交叉 ---
rows = []
for bpath, bmd5 in sorted(board.items()):
    name = os.path.basename(bpath)
    cands = repo_by_name.get(name, [])
    match = [r for r, m, s in cands if m == bmd5]
    stale = [(r, m) for r, m in ((r, m) for r, m, s in cands) if m != bmd5]
    rows.append((name, bpath, bmd5, match, stale, bool(cands)))

# --- 报告 ---
out = []
out.append("== 一、板上有、仓库也有同名文件：按 md5 判定哪个是「板上那份」 ==")
out.append("")
ok = warn = 0
for name, bpath, bmd5, match, stale, has in rows:
    if not has:
        continue
    if match:
        ok += 1
        flag = "OK  "
    else:
        warn += 1
        flag = "★漂移"
    out.append("%s %-32s 板上 %s  %s" % (flag, name, bmd5[:8], bpath))
    for r in match:
        out.append("         └ 与板上一致 → %s" % r)
    for r, m in stale:
        out.append("         └ 旧/异 (%s) → %s" % (m[:8], r))
out.append("")
out.append("  小计：仓库有对应副本且**与板上一致** %d 个；**没有一个副本与板上一致** %d 个" % (ok, warn))

out.append("")
out.append("== 二、板上有、但仓库里【没有任何同名文件】 ==")
only = [r for r in rows if not r[5]]
out.append("  共 %d 个（这些只存在于 工具/板端脚本快照_20261015/ 或根本没归档）" % len(only))
for name, bpath, bmd5, match, stale, has in only:
    alt = repo_md5.get(bmd5)
    tag = ("  ← 内容相同但文件名不同: %s" % alt) if alt else ""
    out.append("    %s  %s%s" % (bmd5[:8], bpath, tag))

out.append("")
out.append("== 三、名字不同但内容相同（板端改名了）==")
for name, bpath, bmd5, match, stale, has in rows:
    if not has and bmd5 in repo_md5:
        out.append("    板上 %s\n      == 仓库 %s" % (bpath, repo_md5[bmd5]))

txt = "\n".join(out)
open(r"E:\fudanwei\_scripts\match_out.txt", "w", encoding="utf-8").write(txt)
print("written, %d lines" % len(out))
