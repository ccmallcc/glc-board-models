#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""恢复 + 正确地给「相位操作数对比」加 DIFF 守卫。

上一版把块尾算错（say(...) 的续行没算进去），把 else: 插进了 say() 调用中间。
这次按"从 rsym 行到出现 else "不同", nc)) 那一行为止"来定块尾。
"""
import io
import shutil
import sys

P = '/root/glc/glc_board_full.py'
BAK = P + '.bak_diff'

mode = sys.argv[1] if len(sys.argv) > 1 else 'patch'

if mode == 'restore':
    shutil.copyfile(BAK, P)
    print('  已从 %s 恢复' % BAK)
    sys.exit(0)

# ---- 1) 先恢复到原始版本，避免在坏文件上继续改 ----
shutil.copyfile(BAK, P)
print('  已恢复原始版本')

lines = io.open(P, encoding='utf-8').read().split('\n')

# ---- 2) 找 rsym 块 ----
idx = None
for i, ln in enumerate(lines):
    if ln.startswith('        rsym') and 'np.fromfile(' in ln:
        idx = i
        break
if idx is None:
    print('  !! 没找到 rsym 行'); sys.exit(1)

end = None
for j in range(idx, min(idx + 20, len(lines))):
    if 'else "不同", nc))' in lines[j]:
        end = j
        break
if end is None:
    print('  !! 没找到块尾'); sys.exit(1)

block = lines[idx:end + 1]
print('  块: 行 %d..%d（共 %d 行）' % (idx + 1, end + 1, len(block)))
assert block[0].startswith('        rsym'), block[0]

new = ['        if DIFF:'] + ['    ' + ln for ln in block]
new += ['        else:',
        '            say("   phase %d: %6d 符号 (参考对比已关，GLC_VERBOSE_DIFF=1 可开)" % (k, sym.size))']
lines = lines[:idx] + new + lines[end + 1:]
io.open(P, 'w', encoding='utf-8', newline='\n').write('\n'.join(lines))
print('  OK  已加守卫')
print('PATCH_OK')
