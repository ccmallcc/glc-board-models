#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench_rgb565.py —— 几种「正确的」BGR->RGB565 写法速度对比（2026-10-14）

前提：只有「通道2置高位」是正确的打包（见 rgb_order_test2.py 的三色验证）。
      cv2.COLOR_BGR2BGR565 经实测**不正确**（纯红给 0x0000），不能用。
本脚本只比**正确的**几种写法，看哪种最快。
"""
import time

import numpy as np

N = 1024 * 600
rng = np.random.RandomState(0)
img = rng.randint(0, 256, (600, 1024, 3), dtype=np.uint8)

# 预计算查表
LUT_R = ((np.arange(256, dtype=np.uint16) >> 3) << 11)
LUT_G = ((np.arange(256, dtype=np.uint16) >> 2) << 5)
LUT_B = (np.arange(256, dtype=np.uint16) >> 3)


def v1_astype3(a):
    """原始写法：三次 astype"""
    return (((a[:, :, 2].astype(np.uint16) >> 3) << 11)
            | ((a[:, :, 1].astype(np.uint16) >> 2) << 5)
            | (a[:, :, 0].astype(np.uint16) >> 3)).astype(np.uint16)


def v2_astype1(a):
    """一次 astype（当前 cam_to_hdmi.py 用的）"""
    u = a.astype(np.uint16)
    return (((u[:, :, 2] >> 3) << 11) | ((u[:, :, 1] >> 2) << 5)
            | (u[:, :, 0] >> 3)).astype(np.uint16)


def v3_lut(a):
    """查表法"""
    return (LUT_R[a[:, :, 2]] | LUT_G[a[:, :, 1]] | LUT_B[a[:, :, 0]])


def v4_lut_out(a, out):
    """查表 + 写进预分配输出（避免临时数组叠加）"""
    np.bitwise_or(LUT_R[a[:, :, 2]], LUT_G[a[:, :, 1]], out=out)
    np.bitwise_or(out, LUT_B[a[:, :, 0]], out=out)
    return out


def v5_view32(a):
    """把 BGR 三通道按 uint32 视图处理（需要 4 字节对齐，这里行不连续，只做尝试）"""
    u = np.ascontiguousarray(a).view(np.uint32).reshape(a.shape[0], a.shape[1])
    # 小端：byte0=B byte1=G byte2=R
    return ((((u >> 16) & 0xFF) >> 3) << 11 | (((u >> 8) & 0xFF) >> 2) << 5
            | ((u & 0xFF) >> 3)).astype(np.uint16)


outbuf = np.empty((600, 1024), np.uint16)
ref = v1_astype3(img)

cases = [("v1 三次 astype（原始）", lambda: v1_astype3(img)),
         ("v2 一次 astype（现用）", lambda: v2_astype1(img)),
         ("v3 查表法", lambda: v3_lut(img)),
         ("v4 查表+预分配输出", lambda: v4_lut_out(img, outbuf)),
         ("v5 uint32 视图", lambda: v5_view32(img))]
print("  基准：129,928,192 字节/次？（实际 1024x600 一帧）")
print("  " + "-" * 76)
for nm, fn in cases:
    try:
        r = fn()
        same = np.array_equal(np.asarray(r).ravel()[:N * 3 // 3], ref.ravel()[:N * 3 // 3]) \
            if np.asarray(r).size == ref.size else False
        n = 8
        t0 = time.time()
        for _ in range(n):
            fn()
        dt = (time.time() - t0) / n
        print("  %-26s %7.2f ms   与 v1 结果相同 = %s" % (nm, dt * 1000, same))
    except Exception as e:
        print("  %-26s 失败: %s" % (nm, str(e)[:50]))
print("BENCH_DONE")
