#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""① 修 send_image.sh 里过时的耗时文案
   ② 把 speed_setup.sh 挂进 /etc/rc.local（掉电重启后自动恢复 tmpfs 设置）"""
import io
import os

BASE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- ① 文案
p = os.path.join(BASE, 'send_image.sh')
s = io.open(p, encoding='utf-8').read()
pairs = [
    ('echo "  编码方式  : 常驻批处理（每张 ~1.05 s + 一次引擎载入）"',
     'echo "  编码方式  : 常驻批处理（每张 ~0.71 s(PL) / ~0.89 s(CPU) + 一次引擎载入 ~6.7 s）"'),
    ('#      ② --batch（默认）  一次性批处理：首张付一次引擎载入（冷 ~13 s / 热 ~6.6 s），\n'
     '#                          之后每张 ~1.05 s。跑完就退，不留常驻句柄。',
     '#      ② --batch（默认）  一次性批处理：首张付一次引擎载入（冷 ~13 s / 热 ~6.7 s），\n'
     '#                          之后每张 ~0.71 s（PL rANS）/ ~0.89 s（CPU 打包）。跑完就退。'),
]
for a, b in pairs:
    if a in s:
        s = s.replace(a, b, 1)
        print('  OK  文案: %s' % a[:40])
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)

# ---------------------------------------------------------------- ② rc.local
rc = os.path.join(BASE, 'rc.local.new')
body = io.open(rc, encoding='utf-8', newline='\n').read() if os.path.exists(rc) else None
print('  rc.local 模板: %s' % ('已读' if body else '缺'))
print('PATCH2_OK')
