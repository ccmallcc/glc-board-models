#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫板子上被"零填充"损坏的文件（ext4 掉电典型症状：size 在、数据块全 0）。

判据说明：
  - size == 0 的**正常空文件**跳过（不算损坏）。
  - size <= FULL_MAX 的整读，**全部字节为 0** ⇒ ALLNUL。
  - 更大的只读头部 HEAD 字节，全 0 ⇒ SUSPECT（不武断定罪）。
  - 只报结果，不修任何东西。
"""
import os

ROOTS = ['/root', '/etc', '/usr/local', '/opt', '/home', '/var/log']
FULL_MAX = 4 * 1024 * 1024          # 4 MB 以内整读
HEAD = 256 * 1024                   # 更大的只看头 256 KB
SKIP_SUB = ('/.git/', '/__pycache__/', '/.cache/')

allnul, suspect, scanned, skipped_big = [], [], 0, 0

for root in ROOTS:
    for dp, dn, fn in os.walk(root):
        if any(s in dp + '/' for s in SKIP_SUB):
            continue
        for name in fn:
            p = os.path.join(dp, name)
            try:
                st = os.lstat(p)
                if not os.path.isfile(p) or st.st_size == 0:
                    continue
                scanned += 1
                if st.st_size <= FULL_MAX:
                    with open(p, 'rb') as fh:
                        data = fh.read()
                    if data and data.count(0) == len(data):
                        allnul.append((st.st_size, p))
                else:
                    skipped_big += 1
                    with open(p, 'rb') as fh:
                        head = fh.read(HEAD)
                    if head and head.count(0) == len(head):
                        suspect.append((st.st_size, p))
            except OSError:
                pass

print("== 扫描结果 ==")
print("  检查文件数            : %d" % scanned)
print("  其中 >4MB 只查了头部  : %d" % skipped_big)
print("  ★ 全 NUL（确认损坏）  : %d" % len(allnul))
print("  ? 头部全 NUL（疑似）  : %d" % len(suspect))
print()
for sz, p in sorted(allnul, reverse=True):
    print("  ALLNUL   %10d B  %s" % (sz, p))
for sz, p in sorted(suspect, reverse=True):
    print("  SUSPECT  %10d B  %s" % (sz, p))
