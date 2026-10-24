#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""验证：build_index 的 (N x 63) 广播比较 能不能用 searchsorted 等价替换。

原实现：
    sc  = max(scales, GLC_SCALE_BOUND)
    cnt = (sc[:,None] <= TABLE[None,:63]).sum(axis=1)
    ret = 63 - cnt

若 TABLE[:63] 是**升序**，则
    #{j : TABLE[j] >= sc} = 63 - searchsorted(TABLE[:63], sc, 'left')
    cnt = 63 - searchsorted(...)
    ret = 63 - cnt = searchsorted(TABLE[:63], sc, 'left')

⇒ 只需证明：与真实数据逐元素相等 + TABLE[:63] 升序。
用板子上真实的 p{k}_scales.f32（4 个相位各 16384 个）来验。
"""
import glob
import os
import sys

import numpy as np

sys.path.insert(0, '/root/glc')
import glc_board_full as G

TB = np.asarray(G.GLC_SCALE_TABLE)
BD = G.GLC_SCALE_BOUND
print('  GLC_SCALE_TABLE: 长度 %d  dtype %s' % (TB.size, TB.dtype))
print('    前 8 个: %s' % TB[:8])
print('    后 8 个: %s' % TB[-8:])
asc = bool(np.all(np.diff(TB[:63]) >= 0))
print('    **TABLE[:63] 是否升序: %s**  ← searchsorted 的前提' % asc)
print('    GLC_SCALE_BOUND = %r' % (BD,))
print('    len(TABLE[:63]) = %d' % len(TB[:63]))
print()


def old(scales):
    sc = np.asarray(scales, dtype=np.float32)
    sc = np.where(sc > BD, sc, BD)
    cnt = (sc[:, None] <= TB[None, :63]).sum(axis=1)
    return (63 - cnt).astype(np.uint32)


def new(scales):
    sc = np.asarray(scales, dtype=np.float32)
    sc = np.where(sc > BD, sc, BD)
    return np.searchsorted(TB[:63], sc, side='left').astype(np.uint32)


# 1) 真实数据
files = sorted(glob.glob('/dev/shm/glc_pack/p*_scales.f32')) + \
        sorted(glob.glob('/dev/shm/glc_pack/p*_scales_raw.f32'))
if not files:
    files = sorted(glob.glob('/root/glc/pack/full_img0/p*_scales*.f32'))
print('  用 %d 个真实 scales 文件验证' % len(files))

total = 0
bad = 0
for f in files:
    a = np.fromfile(f, dtype=np.float32)
    if a.size == 0:
        continue
    o = old(a)
    n = new(a)
    neq = int((o != n).sum())
    total += a.size
    bad += neq
    print('    %-40s n=%6d  不等 %d' % (os.path.basename(f), a.size, neq))

# 2) 随机 + 边界压力测试
rng = np.random.RandomState(0)
cases = [
    ('随机 [0,200]', rng.uniform(0, 200, 20000).astype(np.float32)),
    ('随机 [0,1]', rng.uniform(0, 1, 20000).astype(np.float32)),
    ('全部 = BOUND', np.full(10000, BD, dtype=np.float32)),
    ('全部 = 表里每个值', np.repeat(TB[:64].astype(np.float32), 200)),
    ('极小值', np.full(1000, -1e9, dtype=np.float32)),
    ('极大值', np.full(1000, 1e9, dtype=np.float32)),
    ('恰好卡在表值上', np.tile(TB[:63].astype(np.float32), 300)),
]
for tag, a in cases:
    o = old(a)
    n = new(a)
    neq = int((o != n).sum())
    total += a.size
    bad += neq
    print('    [压力] %-20s n=%6d  不等 %d' % (tag, a.size, neq))

print()
if bad == 0:
    print('  ==> ✅ **逐元素完全等价**（共 %d 个样本，0 个不等）' % total)
    print('      ⇒ 可以安全地把 build_index 换成 searchsorted')
    sys.exit(0)
else:
    print('  ==> ❌ 有 %d 个不等 —— **不能替换**' % bad)
    sys.exit(1)
