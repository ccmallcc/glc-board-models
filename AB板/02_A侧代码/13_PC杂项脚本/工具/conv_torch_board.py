#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""板端 torch(aarch64) 算的 1x1 卷积，能否与 PC torch(x86) 逐位一致？

若能 -> 把这一步换成板端 torch，整条板端链路就与 PC 链路**逐位等价**。
若不能 -> 只能如实报告"两边是数值后端差异，各自自洽"。
"""
import numpy as np
import torch
import torch.nn.functional as F

P = "/root/glc/pack/full_img0"
W = np.load("/root/glc/consts/ysp_reduce_w.npy")   # (256,768,1,1)
B = np.load("/root/glc/consts/ysp_reduce_b.npy")   # (256,)
params = np.load(P + "/params.npy")                # (1,768,16,16)
ref_torch = np.load(P + "/common_torch.npy")       # PC torch 算的（来自 run/ 链路）
ref_np = np.load(P + "/common_np.npy")             # 本脚本 numpy 算的

with torch.no_grad():
    out = F.conv2d(torch.from_numpy(params), torch.from_numpy(W),
                   torch.from_numpy(B)).numpy()

print("torch 版本", torch.__version__)
print("params", params.shape, "-> out", out.shape)


def cmp(tag, a, b):
    nd = int((a != b).sum())
    mx = float(np.abs(a.astype(np.float64) - b.astype(np.float64)).max())
    print("  %-40s 不同 %6d/%d  最大绝对差 %.3e  %s"
          % (tag, nd, a.size, mx, "**逐位一致**" if nd == 0 else ""))


cmp("板端 torch vs PC torch (common_torch)", out, ref_torch)
cmp("板端 torch vs 板端 numpy (common_np)", out, ref_np)
