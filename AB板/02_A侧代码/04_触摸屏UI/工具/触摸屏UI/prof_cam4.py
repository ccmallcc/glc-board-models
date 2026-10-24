#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""prof_cam4.py —— 查"卡顿"到底是帧率低还是延迟高

背景矛盾：UI 主循环实测 43 ms/帧（≈23 fps），但屏上 fps 字段长期显示 5~6。
而且实测 cap.grab() 单次要 50 ms（相机标称 30 fps = 33 ms/帧），
UI 里 cap.read() 却只有 19~26 ms —— **比相机能出帧的速度还快**，
这说明 read() 很可能是在**重复返回驱动缓冲里的旧帧**（快的假象，表现为卡顿）。

本脚本量三件事：
  ① cap.read() 的时间分布
  ② **去重后的真实更新率**（连续两帧是否同一张）—— 这才是"看起来几帧"
  ③ 完整复现 UI 主循环，看端到端到底多少帧
"""
import hashlib
import time

import cv2
import numpy as np

W, H = 1024, 600
BUF = W * H * 2
PW, PH = 610, 458
N = 60


def main():
    cap = cv2.VideoCapture(1)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    for _ in range(8):
        cap.read()
    print("相机 %.0fx%.0f 标称 %.0f fps"
          % (cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT),
             cap.get(cv2.CAP_PROP_FPS)))

    # ---------- ① read() 时间分布 + ② 去重 ----------
    print("\n=== ①+② 连续 %d 次 cap.read() ===" % N)
    ts, sigs = [], []
    t_all = time.time()
    for _ in range(N):
        t = time.time()
        ok, f = cap.read()
        ts.append((time.time() - t) * 1000)
        if ok:
            sigs.append(hashlib.md5(f[::8, ::8].tobytes()).hexdigest()[:8])
    wall = time.time() - t_all
    ts = np.array(ts)
    uniq = len(set(sigs))
    # 相邻两帧相同 = 又读了一遍同一张
    dup = sum(1 for i in range(1, len(sigs)) if sigs[i] == sigs[i - 1])
    print("  墙钟 %.2f s  ⇒ %.2f 次/s（这是 read() 的调用速率，不是画面更新率）"
          % (wall, N / wall))
    print("  read()  中位 %.1f ms  均值 %.1f  最小 %.1f  最大 %.1f"
          % (np.median(ts), ts.mean(), ts.min(), ts.max()))
    print("  ★ 去重后不同画面 = %d / %d  ⇒ **画面真实更新率 ≈ %.1f fps**"
          % (uniq, len(sigs), uniq / wall))
    print("  ★ 相邻重复 = %d 次 / %d  (%.0f%%)  <- 重复越高越'卡'"
          % (dup, len(sigs) - 1, 100.0 * dup / max(1, len(sigs) - 1)))

    # ---------- ③ 完整复现 UI 主循环 ----------
    print("\n=== ③ 复现 UI 主循环（read + EV + resize + RGB565 + tobytes）===")
    canvas = np.zeros((H, W, 3), np.uint8)
    u16 = np.zeros((H, W), np.uint16)
    lut = np.arange(256, dtype=np.uint8)
    t0 = time.time()
    n = 0
    sig2 = []
    for _ in range(40):
        ok, f = cap.read()
        if not ok:
            continue
        f = cv2.LUT(f, lut)
        r = cv2.resize(f, (PW, PH), interpolation=cv2.INTER_AREA)
        canvas[46:504, 207:817] = r
        a = canvas[46:504, 207:817].astype(np.uint16)
        u16[46:504, 207:817] = (((a[:, :, 2] >> 3) << 11) | ((a[:, :, 1] >> 2) << 5)
                                | (a[:, :, 0] >> 3))
        raw = u16.tobytes()
        sig2.append(hashlib.md5(raw[::997]).hexdigest()[:8])
        n += 1
    wall2 = time.time() - t0
    print("  %d 帧 / %.2f s = **%.1f fps**（含全部像素处理，不含写 udma）" % (n, wall2, n / wall2))

    # ---------- 试试降低请求帧率 / 换更小分辨率 ----------
    print("\n=== ④ 试几种配置（看哪种'去重后更新率'最高、延迟最低）===")
    for (cw, ch, fps) in ((640, 480, 30), (640, 480, 15), (640, 360, 30), (432, 240, 30)):
        cap.release()
        c = cv2.VideoCapture(1)
        c.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        c.set(cv2.CAP_PROP_FRAME_WIDTH, cw)
        c.set(cv2.CAP_PROP_FRAME_HEIGHT, ch)
        c.set(cv2.CAP_PROP_FPS, fps)
        c.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        for _ in range(8):
            c.read()
        s, t0 = [], time.time()
        for _ in range(30):
            ok, f = c.read()
            if ok:
                s.append(hashlib.md5(f[::8, ::8].tobytes()).hexdigest()[:8])
        el = time.time() - t0
        real_w = c.get(cv2.CAP_PROP_FRAME_WIDTH)
        real_h = c.get(cv2.CAP_PROP_FRAME_HEIGHT)
        print("  请求 %dx%d@%d -> 实得 %.0fx%.0f  读 %d 帧 / %.2fs = %.1f 次/s  "
              "去重后 %.1f fps (重复 %d)"
              % (cw, ch, fps, real_w, real_h, len(s), el, len(s) / el,
                 len(set(s)) / el, sum(1 for i in range(1, len(s)) if s[i] == s[i - 1])))
        c.release()
    print("\nPROF4_DONE")


if __name__ == "__main__":
    main()
