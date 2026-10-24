#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""把 build_index 的 (N,63) 广播比较换成 searchsorted。

已逐元素验证等价（verify_build_index.py：411,380 个样本 0 不等，
含"恰好卡在表值上""全部=BOUND""极值"等边界压力测试）。
"""
import io
import shutil
import sys

P = sys.argv[1] if len(sys.argv) > 1 else '/root/glc/glc_board_full.py'
BAK = P + '.bak_bidx'

if len(sys.argv) > 2 and sys.argv[2] == 'restore':
    shutil.copyfile(BAK, P)
    print('  已从备份恢复')
    sys.exit(0)

s = io.open(P, encoding='utf-8').read()

OLD = ('def build_index(scales):\n'
       '    sc = np.asarray(scales, dtype=np.float32)\n'
       '    sc = np.where(sc > GLC_SCALE_BOUND, sc, GLC_SCALE_BOUND)\n'
       '    cnt = (sc[:, None] <= GLC_SCALE_TABLE[None, :63]).sum(axis=1)\n'
       '    return (63 - cnt).astype(np.uint32)')

NEW = ('def build_index(scales):\n'
       '    """把 scale 映射到码表下标（0..63）。\n'
       '\n'
       '    ★ 2026-09-23 等价替换：原实现建一个 (N, 63) 的布尔矩阵再 sum(axis=1)。\n'
       '      每相位 N = 65536/4 = 16384 ⇒ 单相位 103 万个元素的临时数组，\n'
       '      4 个相位合计每张图 400 万个元素（实测占每张编码时间 ~7%）。\n'
       '\n'
       '      GLC_SCALE_TABLE[:63] 实测**严格升序**（0.11 → 226.359），因此\n'
       '          cnt[i] = #{j<63 : TABLE[j] >= sc[i]} = 63 - searchsorted(TABLE[:63], sc[i], "left")\n'
       '          返回 63 - cnt  ⇒  **恰好等于 searchsorted(TABLE[:63], sc, "left")**\n'
       '      已用 411,380 个样本（真实 scales + 7 组边界压力）逐元素验证：0 个不等。\n'
       '      见 工具/板端脚本/verify_build_index.py。\n'
       '    """\n'
       '    sc = np.asarray(scales, dtype=np.float32)\n'
       '    sc = np.where(sc > GLC_SCALE_BOUND, sc, GLC_SCALE_BOUND)\n'
       '    return np.searchsorted(GLC_SCALE_TABLE[:63], sc, side="left").astype(np.uint32)')

if 'searchsorted' in s:
    print('  已经改过了')
    sys.exit(0)
if OLD not in s:
    print('  !! 没找到 build_index 原文（可能已被改动）')
    sys.exit(1)

s = s.replace(OLD, NEW, 1)
io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
print('  OK  build_index 已换成 searchsorted')
print('PATCH_OK')
