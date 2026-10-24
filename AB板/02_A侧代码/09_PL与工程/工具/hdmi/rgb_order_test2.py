#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rgb_order_test2.py —— 用足够大的图判定 RGB565 通道顺序（2026-10-14）

⚠️ 第一版用 1x1 图，命中 OpenCV SIMD 边缘情况，纯红给出 0x0000（明显是错的）。
   本版用 64x64。

判据：PL 要的是 **R 在 bit11-15**（依据：hdmi-show-1024x600.py 用 PIL 的 RGB 输入
      喂同一个公式，官方 demo 靠它出图）。
      ⇒ 纯红应得 0xF800，纯绿 0x07E0，纯蓝 0x001F。
      而 cv2 读出来是 **BGR**，所以通道 2 才是 R。
"""
import numpy as np
import cv2

N = 64


def A_ch0_high(a):
    """hdmi-show-1024x600.py 的公式（假设输入是 RGB）"""
    return (((a[:, :, 0].astype(np.uint16) >> 3) << 11)
            | ((a[:, :, 1].astype(np.uint16) >> 2) << 5)
            | (a[:, :, 2].astype(np.uint16) >> 3)).astype(np.uint16)


def B_ch2_high(a):
    """同一公式，但按 cv2 的 BGR：通道 2 = R"""
    return (((a[:, :, 2].astype(np.uint16) >> 3) << 11)
            | ((a[:, :, 1].astype(np.uint16) >> 2) << 5)
            | (a[:, :, 0].astype(np.uint16) >> 3)).astype(np.uint16)


def C_cv2(a):
    return cv2.cvtColor(a, cv2.COLOR_BGR2BGR565)


cases = [("纯红 BGR(0,0,255)", (0, 0, 255), 0xF800),
         ("纯绿 BGR(0,255,0)", (0, 255, 0), 0x07E0),
         ("纯蓝 BGR(255,0,0)", (255, 0, 0), 0x001F)]
print("  期望：纯红=0xF800 纯绿=0x07E0 纯蓝=0x001F   （R 在 bit11-15）")
print("  " + "-" * 84)
print("  %-18s %-16s %-16s %-16s %s" % ("输入(cv2 BGR)", "A:通道0置高", "B:通道2置高", "C:cv2内置", "正确答案"))
for nm, bgr, want in cases:
    a = np.zeros((N, N, 3), np.uint8)
    a[:, :] = bgr
    x = int(np.asarray(A_ch0_high(a)).ravel()[0])
    y = int(np.asarray(B_ch2_high(a)).ravel()[0])
    z = int(np.asarray(C_cv2(a)).ravel()[0])
    m = lambda v: "✓" if v == want else "✗"
    print("  %-18s 0x%04X %s      0x%04X %s      0x%04X %s      0x%04X"
          % (nm, x, m(x), y, m(y), z, m(z), want))

print()
print("  ---- 在大图上再对一次（64x64 随机噪声）----")
rng = np.random.RandomState(0)
a = rng.randint(0, 256, (N, N, 3), dtype=np.uint8)
A1, B1, C1 = A_ch0_high(a), B_ch2_high(a), C_cv2(a)
print("    B(通道2置高) 与 A(通道0置高) 逐字节相同 =", np.array_equal(A1, B1), "（应 False，红蓝互换）")
print("    C(cv2内置)   与 B(通道2置高) 逐字节相同 =", np.array_equal(C1, B1))
print("    C(cv2内置)   与 A(通道0置高) 逐字节相同 =", np.array_equal(C1, A1))
print("    ⇒ 若 C==B，则 cv2 内置可以替代 B")
print("RGB_ORDER_TEST2_DONE")
