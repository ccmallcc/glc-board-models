#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐目录统计「git blob 与工作区字节不一致」的文件数 —— 交付包字节保真的体检。

为什么要它：`.gitattributes` 里对冻结交付包写了 `-text`（禁止任何行尾转换），
理由是包内 `校验清单_md5.txt` 记录了**工作区字节**的 md5，一旦转换就核不上。
V9 那个包漏了这条规则 ⇒ 1 个文件有隐患（2026-10-15 实测发现）。

方法自证（先跑一遍已知案例，方法不对就停）：
  已知：assets/V8显示端配置_给B/rtl/frame_to_ps_largebuf.v 应 **一致**（有 -text）
        assets/V9显示端配置_1024x600/frame_to_ps_largebuf.v 应 **不一致**（缺 -text）
"""
import os
import sys
import hashlib
import subprocess

REPO = r"E:\fudanwei\GLC-共享包"


def md5b(b):
    return hashlib.md5(b).hexdigest()


def blob(rel):
    r = subprocess.run(['git', '-C', REPO, 'show', 'HEAD:' + rel], capture_output=True)
    return md5b(r.stdout) if r.returncode == 0 else None


def work(rel):
    p = os.path.join(REPO, rel.replace('/', os.sep))
    if not os.path.isfile(p):
        return None
    with open(p, 'rb') as f:
        return md5b(f.read())


def attr(rel):
    r = subprocess.run(['git', '-C', REPO, 'check-attr', 'text', '--', rel],
                       capture_output=True)
    return r.stdout.decode('utf-8', 'replace').rsplit(':', 1)[-1].strip()


# ---- 方法自证 ----
V8 = 'assets/V8显示端配置_给B/rtl/frame_to_ps_largebuf.v'
V9 = 'assets/V9显示端配置_1024x600/frame_to_ps_largebuf.v'
print("== 方法自证（必须先过这一关）==")
for rel, expect in ((V8, '一致'), (V9, '不一致')):
    b, w = blob(rel), work(rel)
    got = '一致' if b == w else '不一致'
    flag = 'OK ' if got == expect else '!!! 方法有问题'
    print("  %-8s %-58s blob=%s work=%s attr=%s" %
          (flag, os.path.basename(os.path.dirname(os.path.dirname(rel))),
           (b or '??')[:8], (w or '??')[:8], attr(rel)))
    if got != expect:
        print("  ⇒ 期望 %s 却得到 %s，停止" % (expect, got))
        sys.exit(1)

# ---- 全 assets 体检 ----
print("\n== assets 各子目录体检 ==")
ls = subprocess.run(['git', '-C', REPO, '-c', 'core.quotepath=false',
                     'ls-files', 'assets/'], capture_output=True)
files = ls.stdout.decode('utf-8', 'replace').splitlines()

from collections import defaultdict
stat = defaultdict(lambda: [0, 0, None])
for rel in files:
    if not os.path.isfile(os.path.join(REPO, rel.replace('/', os.sep))):
        continue
    parts = rel.split('/')
    d = '/'.join(parts[:2]) + '/' if len(parts) >= 2 else rel
    s = stat[d]
    s[0] += 1
    if blob(rel) != work(rel):
        s[1] += 1
    if s[2] is None:
        s[2] = attr(rel)

bad_total = 0
for d in sorted(stat):
    n, bad, at = stat[d]
    tag = ''
    if bad:
        tag = '  ← ★ blob≠工作区'
        bad_total += bad
    prot = '有 -text 保护' if at == 'unset' else ('无规则' if at == 'unspecified' else at)
    print("  %-44s 文件 %3d  不一致 %3d   %s%s" % (d, n, bad, prot, tag))

print("\n  合计不一致: %d 个文件" % bad_total)
