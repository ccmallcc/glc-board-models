#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_draw_touch.py —— 单独验证 draw_touch() 不会在真人第一次触摸时崩掉

draw_touch 只有真实触摸事件才会走到（合成 tap 不更新 touch.last），
所以不在上屏前先单独跑一遍，风险全压在你手指上。
"""
import sys
import time

import numpy as np

sys.path.insert(0, "/root")
import glc_ui  # noqa: E402


class FakeArgs(object):
    show_touch = True
    verbose = False


class FakeTouch(object):
    def __init__(self, x, y, down):
        self.last = (x, y)
        self.raw = (x * 4, y * 4)
        self.last_t = time.time()
        self.is_down = down
        self.n_down = 7


ui = glc_ui.UI.__new__(glc_ui.UI)          # 不走 __init__，不碰硬件
ui.canvas = np.zeros((glc_ui.H, glc_ui.W, 3), np.uint8)

cases = [
    ("屏幕正中", 512, 300, True),
    ("左上角", 2, 2, True),
    ("右下角", 1021, 597, False),
    ("贴着下边栏", 900, 570, True),
    ("贴着右边", 1015, 20, True),
]
ok = True
for name, x, y, down in cases:
    ui.a = FakeArgs()
    ui.touch = FakeTouch(x, y, down)
    ui.canvas[:] = 40
    try:
        ui.draw_touch(ui.canvas)
        d = int(ui.canvas.max()) - 40
        print("  %-12s (%4d,%4d) down=%-5s -> OK  最大亮度增量=%d" % (name, x, y, down, d))
        if d <= 0:
            print("      !! 画了但屏上没变化")
            ok = False
    except Exception as e:
        print("  %-12s (%4d,%4d) -> 崩了: %s: %s" % (name, x, y, type(e).__name__, e))
        ok = False

# 过期后应该什么都不画
ui.touch.last_t = time.time() - 10
ui.canvas[:] = 40
ui.draw_touch(ui.canvas)
print("  过期(10s前) -> %s" % ("正确地不画" if ui.canvas.max() == 40 else "!! 过期了还在画"))

import cv2  # noqa: E402
cv2.imwrite("/root/test_draw_touch.png", ui.canvas)
print("DRAW_TOUCH_TEST %s" % ("PASS" if ok else "FAIL"))
