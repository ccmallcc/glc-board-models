# -*- coding: utf-8 -*-
"""决定性测试：板端胶水层用 numpy 实现，能否与 PC 上 torch 的结果**逐位一致**？

背景：胶水层里唯一"有权重"的一步是
    common = model.y_spatial_prior_reduction(params)   # nn.Conv2d(768, 256, 1)
（common_model.py:74 / image_model.py:74）

其余步骤（chunk / clamp / 倒数 / round / 掩码 / 索引）都是逐元素精确运算，不涉及归约，
numpy 与 torch 必然逐位相同。**只有这个 1x1 卷积有数值归约，是唯一的风险点。**

本脚本用真实形状 (1,768,16,16) -> 256 输出，跑三种 numpy 写法与 torch 对比。
"""
import numpy as np
import torch
import torch.nn.functional as F

CONSTS = "/mnt/e/fudanwei/工作区/_board_run/glue_consts"

W = np.load(CONSTS + "/ysp_reduce_w.npy")   # (256,768,1,1)
B = np.load(CONSTS + "/ysp_reduce_b.npy")   # (256,)

rng = np.random.default_rng(20260926)

# 用真实量级：params 是 S2 的输出，量级按实测量级取 O(1)
x = (rng.standard_normal((1, 768, 16, 16)).astype(np.float32) * 2.0)

# ---- torch 参考（就是 board_e2e.py 走的那条路）----
tw = torch.from_numpy(W).clone()
tb = torch.from_numpy(B).clone()
tx = torch.from_numpy(x).clone()
with torch.no_grad():
    ref = F.conv2d(tx, tw, tb).numpy()

print("torch conv2d  -> shape %s" % (ref.shape,))

variants = {}

# (a) 展平成 GEMM：最接近 torch 的 im2col+addmm
W2 = W.reshape(256, 768).astype(np.float32)
x2 = x.reshape(1, 768, 256)[0]                      # (768, 256)
variants["a_gemm_f32"] = (W2 @ x2 + B[:, None]).reshape(1, 256, 16, 16)

# (b) einsum（不优化，强制按朴素顺序累加）
variants["b_einsum_f32"] = (np.einsum("oc,cp->op", W2, x2, optimize=False)
                            + B[:, None]).reshape(1, 256, 16, 16)

# (c) float64 累加后转回 f32
variants["c_gemm_f64"] = (W2.astype(np.float64) @ x2.astype(np.float64)
                          + B.astype(np.float64)[:, None]).astype(np.float32).reshape(1, 256, 16, 16)

print("\n%-16s %10s %12s %14s" % ("写法", "逐位一致", "最大绝对差", "不同元素数"))
for name, v in variants.items():
    same = np.array_equal(v, ref)
    d = np.abs(v.astype(np.float64) - ref.astype(np.float64))
    nd = int((v != ref).sum())
    print("%-16s %10s %12.3e %14d" % (name, "是" if same else "否", d.max(), nd))

# 还要看：这点差异会不会真的翻转符号？（sym = round(yv - mn)）
print("\n=== 差异传导测试：round(yv - mn) 会不会翻 ===")
base = ref.reshape(-1)
for name, v in variants.items():
    a = np.round(base - 0.0)
    b = np.round(v.reshape(-1) - 0.0)
    print("  %-16s round 翻转 %d / %d 个" % (name, int((a != b).sum()), a.size))
