#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""更新 send_image.sh / enc_batch.sh 里过时的耗时文案。"""
import io
import os

BASE = os.path.dirname(os.path.abspath(__file__))
PAIRS = [
    ('每张 ~0.71 s(PL) / ~0.89 s(CPU) + 一次引擎载入 ~6.7 s',
     '每张 ~0.60 s(PL) / ~0.89 s(CPU) + 一次引擎载入 ~6.7 s'),
    ('#     指纹 = 0x20260922（我们的 rans_top）⇒ glc_batch_rsd.py  PL rANS   0.714 s/张',
     '#     指纹 = 0x20260922（我们的 rans_top）⇒ glc_batch_rsd.py  PL rANS   0.60 s/张'),
    ('#     指纹 = 0x20260922（我们的 rans_top）⇒ glc_batch_rsd.py  PL rANS  0.715 s/张',
     '#     指纹 = 0x20260922（我们的 rans_top）⇒ glc_batch_rsd.py  PL rANS  0.60 s/张'),
    ('# 1.192 s/张', '# 0.595 s/张（20.2×）'),
]
for fn in ('send_image.sh', 'enc_batch.sh'):
    p = os.path.join(BASE, fn)
    if not os.path.exists(p):
        continue
    s = io.open(p, encoding='utf-8').read()
    n = 0
    for a, b in PAIRS:
        if a in s:
            s = s.replace(a, b)
            n += 1
    if n:
        io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('  %-16s 改了 %d 处' % (fn, n))
print('OK')
