#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""矛盾排查：为什么 z_hat 逐位一致，z_idx 却与 pack/img0 的参考不同？

三个互斥假设，用数据判定：
  H1 码本有重复向量 -> codebook[ref_idx] == codebook[my_idx] 成立，但 idx 不同
  H2 run/ 与 pack/img0 不是同一次链路 -> codebook[ref_idx] != codebook[my_idx]
  H3 参考 z_indices 另有来源
"""
import numpy as np

C = "/root/glc/consts"
P = "/root/glc/pack"
REF = "/root/glc/ref_stage"

cb = np.load(C + "/z_codebook.npy")
print("码本形状", cb.shape)

my = np.array([14729, 2245, 11439, 7733, 9124, 10787, 4160, 11856,
               9987, 6596, 15847, 5949, 1692, 9266, 1692, 9412], dtype=np.int32)
ref = np.fromfile(P + "/img0/z_indices.i32", dtype=np.int32)
print("my  idx:", my.tolist())
print("ref idx:", ref.tolist())

# ---- H1: 码本是否退化（有重复行）----
uniq = np.unique(cb, axis=0)
print("\n码本去重后行数 = %d / %d  -> %s"
      % (uniq.shape[0], cb.shape[0],
         "有重复向量" if uniq.shape[0] < cb.shape[0] else "无重复向量"))
# 我的 z_hat 与参考索引对应的 z_hat 是否相同
a = cb[my]
b = cb[ref]
print("codebook[my] == codebook[ref] ? %s  (最大绝对差 %.3e)"
      % (np.array_equal(a, b), float(np.abs(a.astype(np.float64) - b.astype(np.float64)).max())))

# ---- 直接的 z_hat 对照 ----
staged = np.fromfile(REF + "/run/s2/in0.ftmp", dtype=np.float32).reshape(1, 4, 4, 256)
print("\nstaged(run/s2/in0.ftmp) == codebook[my]  ? %s"
      % np.array_equal(staged, cb[my].reshape(1, 4, 4, 256).astype(np.float32)))
print("staged(run/s2/in0.ftmp) == codebook[ref] ? %s"
      % np.array_equal(staged, cb[ref].reshape(1, 4, 4, 256).astype(np.float32)))

# ---- H2: 原始 scales/means 对照（这是上次漏掉的关键比对）----
for k in range(4):
    for nm in ("scales", "means"):
        f_ref = "%s/pack_img0/p%d_%s_raw.f32" % (REF, k, nm)
        f_my = "%s/full_img0/p%d_%s_raw.f32" % (P, k, nm)
        try:
            x = np.fromfile(f_ref, dtype=np.float32)
            y = np.fromfile(f_my, dtype=np.float32)
            nd = int((x != y).sum())
            mx = float(np.abs(x.astype(np.float64) - y.astype(np.float64)).max())
            print("  %s p%d_%s_raw : 不同 %7d / %d   最大差 %.3e  %s"
                  % ("RAW", k, nm, nd, x.size, mx, "一致" if nd == 0 else ""))
        except Exception as e:
            print("  p%d_%s_raw 读取失败 %s" % (k, nm, e))

# ---- ref_yhat 对照 ----
try:
    ry = np.load(REF + "/pack_img0/ref_yhat.npy")
    print("\npakc_img0/ref_yhat.npy", ry.shape, "range [%.4f, %.4f]"
          % (float(ry.min()), float(ry.max())))
except Exception as e:
    print("ref_yhat 读取失败", e)

# ---- 已有的 sym/scales 差异 ----
for k in range(4):
    x = np.fromfile("%s/pack_img0/p%d_sym.i32" % (REF, k), dtype=np.int32)
    y = np.fromfile("%s/full_img0/p%d_sym.i32" % (P, k), dtype=np.int32)
    print("  sym p%d: 参考 %d 个 in [%d,%d] ; 本脚本 %d 个 in [%d,%d] ; 不同 %d"
          % (k, x.size, x.min(), x.max(), y.size, y.min(), y.max(), int((x != y).sum())))
