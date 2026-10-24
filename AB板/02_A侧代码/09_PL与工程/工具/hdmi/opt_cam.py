#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""opt_cam.py —— 把「摄像头→HDMI」几种优化组合实测对比（2026-10-14）

已测出的瓶颈（prof_cam.py，640x480 MJPG，71 ms/帧）：
    ① cap.read() 取帧+MJPG解码  41.5 ms (58%)
    ② letterbox 缩放合成         9.4 ms (13%)
    ③ RGB565 转换打包           19.2 ms (27%)
    ④ udma 写入                  0.9 ms ( 1%)  ← 完全不是瓶颈（1.34 GB/s）

本脚本测这几项优化：
    A. 基线：手写 numpy RGB565 + 每帧新建 canvas
    B. 用 cv2.cvtColor(COLOR_BGR2BGR565) 代替手写 numpy
    C. canvas 复用（不每帧 np.zeros）
    D. 不放大，1:1 居中显示（省掉 resize）
    E. YUYV 1280x720 直接取（免 MJPG 解码）
    F. MJPG 1024x576（横向不需要缩放）

⚠️ 同时校验 B 与 A 的输出**逐字节相同**——否则不能换。
用法：python3 opt_cam.py
"""
import time

import numpy as np
import cv2

W, H = 1024, 600


def pack_np(a):
    """基线：手写 numpy RGB565"""
    return (((a[:, :, 0].astype(np.uint16) >> 3) << 11)
            | ((a[:, :, 1].astype(np.uint16) >> 2) << 5)
            | (a[:, :, 2].astype(np.uint16) >> 3)).astype(np.uint16).tobytes()


def pack_cv(a):
    """优化：OpenCV 内置转换"""
    return cv2.cvtColor(a, cv2.COLOR_BGR2BGR565).tobytes()


def place(canvas, frame, scale=True):
    """把 frame 贴到 canvas 中央；scale=True 等比放大/缩小，False 时 1:1 居中（超出则裁剪）"""
    fh, fw = frame.shape[:2]
    if scale:
        s = min(W / float(fw), H / float(fh))
        nw, nh = max(1, int(fw * s)), max(1, int(fh * s))
        r = cv2.resize(frame, (nw, nh),
                       interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
    else:
        r = frame if (fw <= W and fh <= H) else frame[:H, :W]
        nh, nw = r.shape[:2]
    y0, x0 = (H - nh) // 2, (W - nw) // 2
    canvas[:] = 0
    canvas[y0:y0 + nh, x0:x0 + nw] = r
    return canvas


def open_cam(dev, fourcc, w, h, fps):
    cap = cv2.VideoCapture(dev)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
    cap.set(cv2.CAP_PROP_FPS, fps)
    return cap


def bench(tag, dev, fourcc, cap_w, cap_h, scale, use_cv, reuse, n=60):
    cap = open_cam(dev, fourcc, cap_w, cap_h, 30)
    got_w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    got_h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    ok, f0 = cap.read()
    if not ok:
        print("  %-34s 读帧失败（格式/尺寸不支持？）" % tag)
        cap.release()
        return
    canvas = np.zeros((H, W, 3), np.uint8)
    t_read = t_conv = 0.0
    for _ in range(n):
        t0 = time.time(); ok, frame = cap.read(); t_read += time.time() - t0
        if not ok:
            continue
        t0 = time.time()
        if fourcc == "YUYV":
            bgr = cv2.cvtColor(frame, cv2.COLOR_YUV2BGR_YUYV)
        else:
            bgr = frame
        cv_ = canvas if reuse else np.zeros((H, W, 3), np.uint8)
        cv_ = place(cv_, bgr, scale)
        raw = pack_cv(cv_) if use_cv else pack_np(cv_)
        t_conv += time.time() - t0
    cap.release()
    tot = t_read + t_conv
    print("  %-34s 实到%4.0fx%-4.0f  取帧%6.1fms 转换%6.1fms  合计%6.1fms  ⇒ %5.1f fps"
          % (tag, got_w, got_h, t_read / n * 1000, t_conv / n * 1000,
             tot / n * 1000, n / tot))


print("=" * 100)
print("  先校验：cv2 转换 vs 手写 numpy，是否逐字节相同")
print("=" * 100)
rng = np.random.RandomState(0)
for nm, a in (("随机噪声", rng.randint(0, 256, (480, 640, 3), dtype=np.uint8)),
              ("渐变色", np.tile(np.arange(256, dtype=np.uint8)[None, :, None], (480, 640, 3))),
              ("全黑", np.zeros((480, 640, 3), np.uint8)),
              ("全白", np.full((480, 640, 3), 255, np.uint8))):
    same = pack_np(a) == pack_cv(a)
    print("  %-10s cv2 与手写 numpy 输出逐字节相同 = %s" % (nm, same))

print()
print("=" * 100)
print("  优化组合实测（每组 60 帧）")
print("=" * 100)
bench("A 基线 MJPG640x480 手写+新建+放大", 1, "MJPG", 640, 480, True, False, False)
bench("B MJPG640x480 cv2转换+新建+放大", 1, "MJPG", 640, 480, True, True, False)
bench("C MJPG640x480 cv2转换+复用+放大", 1, "MJPG", 640, 480, True, True, True)
bench("D MJPG640x480 cv2转换+复用+不放大", 1, "MJPG", 640, 480, False, True, True)
bench("F MJPG1024x576 cv2转换+复用+不放大", 1, "MJPG", 1024, 576, False, True, True)
bench("E YUYV1280x720 cv2转换+复用+缩小", 1, "YUYV", 1280, 720, True, True, True)
print("OPT_DONE")
