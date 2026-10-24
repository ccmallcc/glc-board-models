#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gige_shim.py —— 把 cv2.VideoCapture 换成"读网口相机帧"的假相机

用途：让**完全不用修改**的 glc_ui.py 从网口相机取图。
配合 gige_grab.py（后台连续抓帧，写 /dev/shm/gigecam.*）。

用法（必须早于 glc_ui 导入 cv2 生效）：
    import gige_shim; gige_shim.install()
    # 然后正常跑 glc_ui.py，参数用  --dev /dev/gigecam
    # glc_ui.py 对 "/dev/..." 开头的参数直接采用，不做 v4l2-ctl 探测

★ 2026-10-20 修正（静态检查发现，未修必崩）：
    glc_ui.py 主循环用的是 **cap.grab() + cap.retrieve()**，不是 cap.read()：
        line 509  if not self.cap.grab():
        line 517      ok, f = self.cap.retrieve()
    第一版没实现 retrieve()，且 grab() 把帧丢了 ⇒ AttributeError。
    现在 grab() 取一帧存进 self._pending，retrieve() 取走。
"""
import os
import time

BIN = '/dev/shm/gigecam.bin'
META = '/dev/shm/gigecam.meta'


def _read_meta():
    try:
        with open(META) as f:
            p = f.read().split()
        return int(p[0]), int(p[1]), int(p[2])
    except Exception:
        return None


class FakeCapture(object):
    """形状与 cv2.VideoCapture 一致的替身（覆盖 read/grab/retrieve/set/get/isOpened/release）。"""

    def __init__(self, dev=None, *a, **k):
        self.dev = dev
        self._last_seq = -1
        self._pending = None
        self._w = self._h = 0
        self._ready = False
        t0 = time.time()
        while time.time() - t0 < 10.0:
            m = _read_meta()
            if m:
                self._w, self._h, self._last_seq = m[0], m[1], m[2] - 1
                self._ready = True
                break
            time.sleep(0.05)

    # ---------------- 取帧核心 ----------------
    def _next_frame(self, timeout=3.0):
        """阻塞到出现新帧，返回 (ok, BGR ndarray)。"""
        import numpy as np
        t0 = time.time()
        while time.time() - t0 < timeout:
            m = _read_meta()
            if m and m[2] != self._last_seq:
                w, h, seq = m
                try:
                    with open(BIN, 'rb') as f:
                        data = f.read()
                    if len(data) != w * h * 3:
                        time.sleep(0.01)
                        continue
                    a = np.frombuffer(data, dtype=np.uint8).reshape(h, w, 3)
                    self._last_seq = seq
                    self._w, self._h = w, h
                    return True, a[:, :, ::-1].copy()      # RGB -> BGR
                except Exception:
                    time.sleep(0.01)
                    continue
            time.sleep(0.005)
        return False, None

    # ---------------- VideoCapture 接口 ----------------
    def isOpened(self):
        # ★ Q9-#11：等不到第一帧就返回 False，别把 glc_ui.py 的"打不开"保护架空
        return self._ready

    def grab(self):
        """取一帧放进 _pending，供随后的 retrieve() 取走。"""
        ok, f = self._next_frame()
        self._pending = f if ok else None
        return ok

    def retrieve(self):
        f = self._pending
        self._pending = None
        if f is None:
            return False, None
        return True, f

    def read(self):
        return self._next_frame()

    def get(self, prop):
        # 3=WIDTH 4=HEIGHT 5=FPS
        if prop == 3:
            return float(self._w or 256)
        if prop == 4:
            return float(self._h or 256)
        if prop == 5:
            return 30.0
        return 0.0

    def set(self, *a, **k):
        return True

    def release(self):
        pass


def install():
    """打补丁。返回被替换前的 VideoCapture（便于恢复）。"""
    import cv2
    old = cv2.VideoCapture
    cv2.VideoCapture = FakeCapture
    return old


if __name__ == '__main__':
    # 自检：read 与 grab+retrieve 两条路都要能用
    c = FakeCapture('/dev/gigecam')
    print('opened', c.isOpened(), 'w/h', c.get(3), c.get(4))
    for i in range(2):
        ok, f = c.read()
        print('read ', i, ok, None if f is None else (f.shape, float(f.mean())))
    for i in range(2):
        ok = c.grab()
        ok2, f = c.retrieve()
        print('gr+rt', i, ok, ok2, None if f is None else (f.shape, float(f.mean())))
