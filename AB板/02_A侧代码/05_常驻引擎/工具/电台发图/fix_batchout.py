#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修 bug：PL 路径与 CPU 路径的产物目录不同，send_image.sh / enc_batch.sh 写死了其中一个。

  glc_batch_rsd.py (PL rANS) -> /root/glc/batch_out
  glc_batch_cpu.py (CPU)     -> /root/glc/batch_out_cpu

症状：走 PL 路径时从错误的目录找产物 -> 误判"还缺" -> 再拿单张链重编一遍
      （实测白跑 20 秒；结果虽然是对的，但白等）。
"""
import io
import os

BASE = os.path.dirname(os.path.abspath(__file__))


def patch(fn, pairs):
    p = os.path.join(BASE, fn)
    s = io.open(p, encoding='utf-8').read()
    for a, b, why in pairs:
        if b.split('\n')[0].strip() and a in s and b not in s:
            s = s.replace(a, b, 1)
            print('  OK  %-10s %s' % (fn, why))
        elif b in s:
            print('  --  %-10s %s（已改过）' % (fn, why))
        else:
            print('  !!  %-10s %s 锚点没找到' % (fn, why))
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)


patch('send_image.sh', [
    ('          BATCH_SCRIPT=glc_batch_rsd.py; BATCH_LABEL="PL rANS（FPGA）"\n',
     '          BATCH_SCRIPT=glc_batch_rsd.py; BATCH_LABEL="PL rANS（FPGA）"\n'
     '          BATCH_OUT=$GLC_DIR/batch_out          # rsd 版写这里\n',
     'PL 分支指定 batch_out'),
    ('          BATCH_SCRIPT=glc_batch_cpu.py; BATCH_LABEL="A53 CPU 打包（指纹 $FP）"\n',
     '          BATCH_SCRIPT=glc_batch_cpu.py; BATCH_LABEL="A53 CPU 打包（指纹 $FP）"\n'
     '          BATCH_OUT=$GLC_DIR/batch_out_cpu      # cpu 版写这里\n',
     'CPU 分支指定 batch_out_cpu'),
])

patch('enc_batch.sh', [
    ('if [ "$FORCE" = "pl" ]; then\n'
     '  SCRIPT=glc_batch_rsd.py;  LABEL="PL rANS（FPGA）"\n'
     'else\n'
     '  SCRIPT=glc_batch_cpu.py;  LABEL="A53 CPU 打包"\n'
     'fi',
     'if [ "$FORCE" = "pl" ]; then\n'
     '  SCRIPT=glc_batch_rsd.py;  LABEL="PL rANS（FPGA）"; OUT=$GLC/batch_out\n'
     'else\n'
     '  SCRIPT=glc_batch_cpu.py;  LABEL="A53 CPU 打包";    OUT=$GLC/batch_out_cpu\n'
     'fi',
     '按路径选产物目录'),
])

print('PATCH_OK')
