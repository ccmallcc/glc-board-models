#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""opt_cam2.py —— 补测 YUYV + 量化 cv2 与手写 numpy 的差异（2026-10-14）

① 上一轮 YUYV 报错的原因：OpenCV 的 CAP_PROP_CONVERT_RGB 默认为 1，
   驱动层已经把 YUYV 转成 BGR 交给我们了，不该再 cvtColor 一次。
② cv2.cvtColor(COLOR_BGR2BGR565) 与手写 numpy 在随机噪声下不是逐字节相同，
   本脚本量化到底差在哪、差多少。
"""
import time

import numpy as np
import cv2

W, H = 1024, 600


def pack_np(a):
    return (((a[:, :, 0].astype(np.uint16) >> 3) << 11)
            | ((a[:, :, 1].astype(np.uint16) >> 2) << 5)
            | (a[:, :, 2].astype(np.uint16) >> 3)).astype(np.uint16).tobytes()


def pack_cv(a):
    return cv2.cvtColor(a, cv2.COLOR_BGR2BGR565).tobytes()


print("=" * 92)
print("  ① 量化 cv2 vs 手写 numpy 的差异")
print("=" * 92)
rng = np.random.RandomState(0)
a = rng.randint(0, 256, (64, 64, 3), dtype=np.uint8)
x = np.frombuffer(pack_np(a), dtype=np.uint16)
y = np.frombuffer(pack_cv(a), dtype=np.uint16)
d = (x.astype(np.int32) ^ y.astype(np.int32))
diff = (x != y)
print("  样本 64x64 随机噪声：不同的像素 %d / %d (%.1f%%)" % (diff.sum(), x.size, 100.0 * diff.sum() / x.size))
if diff.sum():
    xr = ((x >> 11) & 0x1F).astype(np.int32); yr = ((y >> 11) & 0x1F).astype(np.int32)
    xg = ((x >> 5) & 0x3F).astype(np.int32);  yg = ((y >> 5) & 0x3F).astype(np.int32)
    xb = (x & 0x1F).astype(np.int32);         yb = (y & 0x1F).astype(np.int32)
    print("    R 通道最大差 %d；G 通道最大差 %d；B 通道最大差 %d"
          % (np.abs(xr - yr).max(), np.abs(xg - yg).max(), np.abs(xb - yb).max()))
    print("    → 手写是截断 (v>>n)，OpenCV 是四舍五入 (round(v*max/255))，差 ≤1 个 LSB")
    print("    肉眼看不出差别；但**不是逐字节相同**，要写进文档。")

print()
print("=" * 92)
print("  ② 补测 YUYV 1280x720（这次不重复转换）")
print("=" * 92)
for fourcc, cw, ch, scale in (("YUYV", 1280, 720, True), ("YUYV", 1280, 720, False),
                              ("MJPG", 640, 480, True)):
    cap = cv2.VideoCapture(1)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, cw)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, ch)
    cap.set(cv2.CAP_PROP_FPS, 30)
    ok, f0 = cap.read()
    if not ok:
        print("  %-6s %dx%d  读帧失败" % (fourcc, cw, ch)); cap.release(); continue
    canvas = np.zeros((H, W, 3), np.uint8)
    n, tr, tc = 40, 0.0, 0.0
    for _ in range(n):
        t0 = time.time(); ok, fr = cap.read(); tr += time.time() - t0
        if not ok:
            continue
        t0 = time.time()
        fh, fw = fr.shape[:2]
        if scale:
            s = min(W / float(fw), H / float(fh))
            nw, nh = max(1, int(fw * s)), max(1, int(fh * s))
            r = cv2.resize(fr, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
        else:
            r = fr if (fw <= W and fh <= H) else fr[:H, :W]
            nh, nw = r.shape[:2]
        canvas[:] = 0
        canvas[(H - nh) // 2:(H - nh) // 2 + nh, (W - nw) // 2:(W - nw) // 2 + nw] = r
        raw = pack_cv(canvas)
        tc += time.time() - t0
    cap.release()
    tot = tr + tc
    print("  %-6s 实到%4.0fx%-4.0f  chan=%d  %s  取帧%6.1fms 转换%6.1fms  合计%6.1fms ⇒ %5.1f fps"
          % (fourcc, f0.shape[1], f0.shape[0], f0.shape[2],
             "放大" if scale else "1:1 ", tr / n * 1000, tc / n * 1000, tot / n * 1000, n / tot))
print("OPT2_DONE")
