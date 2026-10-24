#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修一处措辞：DIFF 关掉时 sym_same/scl_same 恒为 0，
   汇总行会打印 "sym 0/4 一致" —— 读起来像"4 个里有 0 个对上了"，误导。
   改成明确写"未做对比"。"""
import io
import sys

P = sys.argv[1] if len(sys.argv) > 1 else '/root/glc/glc_board_full.py'
s = io.open(P, encoding='utf-8').read()

old = '    say("   操作数 vs PC 链路参考: sym %d/4 一致, scales %d/4 一致" % (sym_same, scl_same))'
new = ('    if os.environ.get(\'GLC_VERBOSE_DIFF\', \'0\') == \'1\':\n'
       '        say("   操作数 vs PC 链路参考: sym %d/4 一致, scales %d/4 一致" % (sym_same, scl_same))\n'
       '    else:\n'
       '        say("   操作数 vs PC 链路参考: 未做对比（置 GLC_VERBOSE_DIFF=1 可开）")')

if new.split('\n')[0] in s:
    print('  已改过')
elif old in s:
    s = s.replace(old, new, 1)
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('  OK  汇总行已改')
else:
    print('  !! 没找到汇总行')
    sys.exit(1)
print('OK')
