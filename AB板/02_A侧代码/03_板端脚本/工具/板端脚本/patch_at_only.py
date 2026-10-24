#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""给 A_send_session.py 加两个开关，让「电台 AT 自检」能与「编码」并行：

  --at-only   只做 清缓冲 + AT 自检 + 进透传，然后退出
  --at-done   跳过上面这段（已经用 --at-only 做过了），直接 BEGIN → 发数据 → END

为什么要拆
----------
实测耗时：AT 自检 **8.23 s**，引擎载入 **6.69 s** —— 两者互不干扰
（一个占串口、一个占 NPU），却现在是串着做的。
拆开后 6.69 s 被 8.23 s 完全盖住 => 发第一张图省约 6.7 s。

用法（send_image.sh 里）
------------------------
    python3 A_send_session.py --at-only &        # 后台
    ...编码...
    wait
    python3 A_send_session.py --at-done <glc...> # 直接发
"""
import io
import shutil
import sys

P = sys.argv[1] if len(sys.argv) > 1 else '/root/A_send_session.py'
BAK = P + '.bak_at'

if len(sys.argv) > 2 and sys.argv[2] == 'restore':
    shutil.copyfile(BAK, P)
    print('  已从备份恢复')
    sys.exit(0)

s = io.open(P, encoding='utf-8').read()

if '--at-only' in s:
    print('  已经打过补丁')
    sys.exit(0)

# ---------- 1) glcs 改成可选（--at-only 时不需要容器）----------
a1 = "    ap.add_argument('glcs', nargs='+')"
b1 = "    ap.add_argument('glcs', nargs='*')"
assert a1 in s, 'glcs 那行没找到'
s = s.replace(a1, b1, 1)
print('  OK  glcs -> nargs=*')

# ---------- 2) 新增两个开关 ----------
a2 = "    ap.add_argument('--retry-rounds', type=int, default=2, help='失败者的补发轮数')"
b2 = (a2 + "\n"
      "    ap.add_argument('--at-only', action='store_true',\n"
      "                    help='只做清缓冲+AT自检+进透传就退出（用于与编码并行）')\n"
      "    ap.add_argument('--at-done', action='store_true',\n"
      "                    help='跳过 AT 自检（已经用 --at-only 做过了）')")
assert a2 in s, 'retry-rounds 那行没找到'
s = s.replace(a2, b2, 1)
print('  OK  新增 --at-only / --at-done')

# ---------- 3) 把 AT 设置整段包进 if not a.at_done: ----------
AT_BLOCK = """    fd = open_dev(115200)
    t_setup = time.time()
    print('[SS] 清缓冲 2.0 s …')
    drain(fd, 2.0)
    at(fd, '+++', 1.5)
    ok = True
    for cmd, want in WANT_AT:
        resp = at_retry(fd, cmd, want, tries=3)
        hit = want in resp
        ok = ok and hit
        print('[SS]   %-11s -> %-46s [%s]' % (cmd, resp.replace('\\n', ' ')[:46], 'OK' if hit else '不符'))
    if not ok:
        print('[SS] 参数不符，不发')
        os.close(fd)
        sys.exit(3)
    r = at(fd, 'AT+EXIT=1', 1.2).decode('utf-8', 'replace').strip()
    print('[SS] AT+EXIT=1 -> %r' % r)
    if 'OK' not in r:
        print('[SS] 没进透传模式')
        os.close(fd)
        sys.exit(6)
    time.sleep(0.5)
    print('[SS] AT 自检一次性耗时 %.2f s' % (time.time() - t_setup))
"""

assert AT_BLOCK in s, 'AT 设置整段没找到（原文可能已改动）'

indented = '\n'.join(('    ' + ln if ln.strip() else ln) for ln in AT_BLOCK.rstrip('\n').split('\n'))
NEW = ("    if a.at_done:\n"
       "        print('[SS] 跳过 AT 自检（--at-done；已由 --at-only 做过）')\n"
       "        fd = open_dev(115200)\n"
       "    else:\n"
       + indented + "\n"
       "    if a.at_only:\n"
       "        print('[SS] --at-only 完成，退出（电台已进透传）')\n"
       "        os.close(fd)\n"
       "        sys.exit(0)\n")

s = s.replace(AT_BLOCK, NEW, 1)
print('  OK  AT 设置段已可跳过 / 可单独执行')

io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
print('PATCH_OK')
