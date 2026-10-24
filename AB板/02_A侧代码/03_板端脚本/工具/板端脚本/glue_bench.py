#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""把编码端的"胶水"逐步计时 —— 判断搬到 FPGA 值不值。

用板子上真实的中间结果（s1 的 y/z、s2 的 params）跑，不构造假数据。
"""
import os
import sys
import time

import numpy as np

sys.path.insert(0, '/root/glc')
import glc_board_full as G

RUN = '/root/glc/run'
S1 = os.path.join(RUN, 's1', 'logs', 's1_encoder_ga_hyper', 'ftmpSFB')
S2 = os.path.join(RUN, 's2', 'logs', 's2_hyperdec_fusion', 'ftmpSFB')


def T(tag, fn, n=3):
    """跑 n 次取中位"""
    ts = []
    r = None
    for _ in range(n):
        t0 = time.time()
        r = fn()
        ts.append(time.time() - t0)
    ts.sort()
    print('  %-46s %8.2f ms' % (tag, ts[len(ts) // 2] * 1000))
    return r


print('=' * 70)
print('编码端"胶水"逐步计时（板端实测，3 次取中位）')
print('=' * 70)

# ---------- 准备真实数据 ----------
fy = os.path.join(S1, '3310.ftmp')
fz = os.path.join(S1, '3314.ftmp')
fp = os.path.join(S2, '184.ftmp')
for f in (fy, fz, fp):
    if not os.path.exists(f):
        print('  !! 缺 %s —— 先跑一次 glc_batch_rsd.py' % f)
        sys.exit(1)

y = np.fromfile(fy, dtype=np.float32).reshape(1, 16, 16, 256)      # y (NHWC)
z = np.fromfile(fz, dtype=np.float32).reshape(1, 4, 4, 256)        # z
params = np.fromfile(fp, dtype=np.float32).reshape(1, 16, 16, 768)  # s2 输出

codebook = np.load('/root/glc/consts/z_codebook.npy')
ysp_w = np.load('/root/glc/consts/ysp_reduce_w.npy')
ysp_b = np.load('/root/glc/consts/ysp_reduce_b.npy')

print('  数据: y%s  z%s  params%s' % (y.shape, z.shape, params.shape))
print('  码本: %s   1x1conv W%s B%s' % (codebook.shape, ysp_w.shape, ysp_b.shape))
K = codebook.shape[0]
print('  ⇒ z_vq 的 argmin 要在 **%d 个码字** 上做，%d 个位置 ⇒ %.1f M MAC'
      % (K, z.reshape(-1, 256).shape[0], z.reshape(-1, 256).shape[0] * K * 256 / 1e6))
print('  ⇒ 1x1 conv: %d x %d x %d = %.1f M MAC' % (256, 768, 256, 256 * 768 * 256 / 1e6))
print()

# ---------- ① z_vq ----------
print('① z_vq（argmin + 查码本）')


def z_vq():
    zz = np.ascontiguousarray(z.transpose(0, 2, 3, 1)).reshape(-1, codebook.shape[1])
    d = (zz ** 2).sum(1, keepdims=True) + (codebook ** 2).sum(1)[None, :] - 2.0 * (zz @ codebook.T)
    return np.argmin(d, axis=1).astype(np.int32)


z_idx = T('  整个 z_vq', z_vq)


def z_vq_matmul():
    zz = np.ascontiguousarray(z.transpose(0, 2, 3, 1)).reshape(-1, codebook.shape[1])
    return zz @ codebook.T


T('  其中：zz @ codebook.T（矩阵乘 %.0fM MAC）' % (16 * K * 256 / 1e6), z_vq_matmul)
print()

# ---------- ② 1x1 conv (y_spatial_prior_reduction) ----------
print('② y_spatial_prior_reduction（1×1 conv，必须与 PC 逐位一致）')


def conv64():
    return (ysp_w.reshape(256,768).astype(np.float64) @ params.reshape(768, -1).astype(np.float64)
            + ysp_b.astype(np.float64)[:, None]).astype(np.float32)


def conv32():
    return (ysp_w.reshape(256,768).astype(np.float32) @ params.reshape(768, -1).astype(np.float32)
            + ysp_b.astype(np.float32)[:, None]).astype(np.float32)


common = T('  float64 累加（当前做法，%.0fM MAC）' % (256 * 768 * 256 / 1e6), conv64)
T('  float32 累加（对照）', conv32)
print()

# ---------- ③ 分相位掩码 + 量化 + compact ----------
print('③ 分相位掩码 + 量化 + compact（4 个相位）')
C, H, W = 256, 16, 16
masks = G.make_masks(C, H, W)
mask_bool = [m.astype(bool) for m in masks]
y_scaled = y.transpose(0, 3, 1, 2).copy()          # 转成 NCHW
sys.path.insert(0, '/root/glc')


def phase_all():
    yh = np.zeros((1, C, H, W), dtype=np.float32)
    for k in range(4):
        m = masks[k]
        means_hat = (params[0, :, :, 0:256].transpose(2, 0, 1)[None] * m).astype(np.float32)
        y_res = ((y_scaled - means_hat) * m).astype(np.float32)
        yh = (yh + np.round(y_res).astype(np.float32) + means_hat).astype(np.float32)
    return yh


T('  4 个相位的掩码+量化+累加', phase_all)
T('  其中：compact()（把掩码位置的元素收集起来）',
  lambda: [G.compact(y_scaled, mask_bool[k]) for k in range(4)])
print()

# ---------- ④ build_index（已经在 PL 侧做，但对照） ----------
print('④ build_index（现在在 PS 做，送进 PL 前）')
sc = np.abs(np.random.randn(16384).astype(np.float32)) * 10 + 0.2
T('  build_index（已换 searchsorted）', lambda: G.build_index(sc))
print()

# ---------- ⑤ PL rANS（对照） ----------
print('⑤ PL rANS 熵编码（已经在 FPGA 里）')
print('  %-46s %8.2f ms   ← 实测' % ('4 个相位 × 16384 符号', 2.918))
print()
print('=' * 70)
print('  结论：把 ①②③ 搬到 PL，每张最多省下上面三项之和')
print('=' * 70)
print('GLUE_BENCH_DONE')
