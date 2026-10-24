#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""量化「校验清单记的是工作区 md5，但队友 clone 拿到的是 blob」这个隐患。

判据：对每个 校验清单_md5.txt，逐条取它记录的 md5，分别与
  ① 工作区文件 md5  ② git blob（HEAD:路径）md5  比对。
  若 ① 中而 ② 不中 ⇒ 队友 clone 后按这份清单核对**必然对不上**。
"""
import os
import re
import sys
import hashlib
import subprocess

REPO = r"E:\fudanwei\GLC-共享包"
# 本仓实测有两种清单格式：
#   ① md5<两空格>字节数<两空格>相对路径      （V8 那份）
#   ② md5<空格>*路径（路径从仓库根算起）     （V9 那份，`md5sum` 的默认输出格式）
LINE = re.compile(r'^([0-9a-f]{32})\s+(?:(\d+)\s+)?(\*?)(\S.*)$')


def md5b(b):
    return hashlib.md5(b).hexdigest()


def md5f(p):
    with open(p, 'rb') as f:
        return md5b(f.read())


def blob_md5(relrepo):
    r = subprocess.run(['git', '-C', REPO, 'show', 'HEAD:' + relrepo],
                       capture_output=True)
    return md5b(r.stdout) if r.returncode == 0 else None


def main():
    manifests = []
    for dp, dn, fn in os.walk(REPO):
        dn[:] = [d for d in dn if d not in ('.git', '__pycache__')]
        for f in fn:
            if '校验清单' in f and f.endswith('.txt'):
                manifests.append(os.path.join(dp, f))

    print("找到 %d 份校验清单\n" % len(manifests))
    total = bad_work = bad_blob = 0
    affected = []
    for m in manifests:
        d = os.path.dirname(m)
        rel_d = os.path.relpath(d, REPO).replace('\\', '/')
        rows = 0
        bad = []
        for ln in open(m, encoding='utf-8', errors='replace'):
            ln = ln.strip()
            mm = LINE.match(ln)
            if not mm:
                continue
            want = mm.group(1)
            star = mm.group(3)
            relp = mm.group(4).strip()
            relp = relp.replace('\\', '/')
            # 格式②：路径从仓库根算起（带 `*` 前缀，或路径以 assets/ 等顶层目录开头）
            if star or relp.startswith('assets/'):
                p = os.path.join(REPO, relp.replace('/', os.sep))
                relrepo = relp
            else:
                p = os.path.join(d, relp.replace('/', os.sep))
                relrepo = (rel_d + '/' + relp) if rel_d != '.' else relp
            if not os.path.isfile(p):
                continue
            rows += 1
            total += 1
            w = md5f(p)
            b = blob_md5(relrepo)
            if w == want and b != want:
                bad.append((relp, want, w, b))
                bad_blob += 1
            elif w != want:
                bad_work += 1
        print("== %s  (%d 条可比对，其中 %d 条 clone 后会对不上)" % (rel_d, rows, len(bad)))
        for relp, want, w, b in bad[:8]:
            print("     %-42s 清单%s  工作区%s  blob%s"
                  % (relp, want[:8], w[:8], (b or '??')[:8]))
        if len(bad) > 8:
            print("     … 另有 %d 条" % (len(bad) - 8))
        if bad:
            affected.append(rel_d)
    print("\n== 汇总 ==")
    print("  可比对条目总数            : %d" % total)
    print("  ★ 清单对、但 clone 后不同 : %d   ← 隐患" % bad_blob)
    print("  清单本身就与工作区不符    : %d" % bad_work)
    print("  受影响的交付目录          : %s" % (', '.join(affected) or '无'))


if __name__ == '__main__':
    main()
