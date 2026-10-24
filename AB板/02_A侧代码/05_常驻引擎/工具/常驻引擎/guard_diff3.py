#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""给 glc_board_full.py 的 5 处「与上次链路 staged 参考做对比」诊断代码加开关。

教训（上一次踩的坑）：
  · 不要引入全局 DIFF —— 插入点若判断错就会 NameError，而且会把编码打断、
    留下残留容器文件，看起来像"跑通了但 md5 错"。
  · 判断"是否已打过补丁"也不能用 'GLC_VERBOSE_DIFF' 这个字符串 —— 守卫的
    else 分支里也会出现它，会误判。改用 'if os.environ.get' 这个特征串。

本版做法：每个点直接内联 `if os.environ.get('GLC_VERBOSE_DIFF','0')=='1':`，
不新增任何名字 => 不可能 NameError。
这些代码只读文件、只打印，不参与计算 => 关掉不改结果。
"""
import io
import shutil
import sys

P = '/root/glc/glc_board_full.py'
BAK = P + '.bak_diff'
GUARD = "if os.environ.get('GLC_VERBOSE_DIFF', '0') == '1':"

if len(sys.argv) > 1 and sys.argv[1] == 'restore':
    shutil.copyfile(BAK, P)
    print('  已从备份恢复')
    sys.exit(0)

s = io.open(P, encoding='utf-8').read()

if GUARD in s:
    print('  已经打过补丁（特征串已存在），退出')
    sys.exit(0)

n_ok = 0


def guard(block, indent, tag):
    """把 block 整体缩进一级，前面加守卫。"""
    global s, n_ok
    if block not in s:
        print('  !! 没找到: %s' % tag)
        return False
    lines = block.rstrip('\n').split('\n')
    new = [indent + GUARD]
    new += ['    ' + ln for ln in lines]
    s = s.replace(block, '\n'.join(new), 1)
    print('  OK  %s' % tag)
    n_ok += 1
    return True


# ---- 1) z_idx 对比 ----
guard('''    ref_zidx = np.fromfile("%s/z_indices.i32" % ref_op, dtype=np.int32)
    say("      本脚本 = %s" % z_idx.tolist())
    say("      参考   = %s" % ref_zidx.tolist())
    say("      -> %s" % ("**一致**" if np.array_equal(z_idx, ref_zidx) else "**不同**"))''',
      '    ', 'z_idx')

# ---- 2) s2 输入对比 ----
guard('''    staged = np.fromfile("%s/run/s2/in0.ftmp" % REF, dtype=np.float32).reshape(1, 4, 4, 256)
    report_diff("s2 输入(z_hat) vs 上次链路staged", z_hat_nhwc, staged)''',
      '    ', 's2 输入')

# ---- 3) common 对比 ----
guard('''    staged_c = np.fromfile("%s/run/s3p1/in1.ftmp" % REF, dtype=np.float32).reshape(1, 16, 16, 256)
    report_diff("common vs 上次链路staged", nhwc(common), staged_c)''',
      '    ', 'common')

# ---- 4) phase0 y_hat 对比 ----
guard('''            if k == 1:
                st = np.fromfile("%s/run/s3p1/in0.ftmp" % REF,
                                 dtype=np.float32).reshape(1, 16, 16, 256)
                report_diff("phase0 后 y_hat_so_far vs 上次链路staged", nhwc(y_hat_so_far), st)''',
      '            ', 'phase0 y_hat')

# ---- 5) 相位操作数对比：按行号定位（字符串匹配在这块一直失败）----
lines = s.split('\n')
i0 = None
for i, ln in enumerate(lines):
    if ln.startswith('        rsym') and 'np.fromfile(' in ln:
        i0 = i
        break
if i0 is None:
    print('  !! 没找到 rsym 行')
else:
    i1 = None
    for j in range(i0, min(i0 + 20, len(lines))):
        if 'else "不同", nc))' in lines[j]:
            i1 = j
            break
    if i1 is None:
        print('  !! 没找到块尾')
    else:
        blk = lines[i0:i1 + 1]
        new = ['        ' + GUARD] + ['    ' + ln for ln in blk]
        new += ['        else:',
                '            say("   phase %d: %6d 符号 (参考对比已关，置 GLC_VERBOSE_DIFF=1 可开)" % (k, sym.size))']
        lines = lines[:i0] + new + lines[i1 + 1:]
        s = '\n'.join(lines)
        print('  OK  相位操作数（行 %d..%d）' % (i0 + 1, i1 + 1))
        n_ok += 1

if n_ok:
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('  已写 %s（%d 处）' % (P, n_ok))
else:
    print('  无改动')
print('PATCH_OK')
