#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prof_cam.py —— 拆开量摄像头→HDMI 每一段的耗时，找瓶颈（2026-10-14）

分段：
  ① cap.read()         V4L2 取帧 + MJPG 解码
  ② letterbox          等比缩放 + 黑边合成
  ③ to_rgb565+tobytes  RGB888 -> RGB565 打包
  ④ chunk.write()      写进 udma 缓冲（PS DDR memcpy）
用法：python3 prof_cam.py [设备号] [帧数] [采集宽 高]
"""
import sys
import time

import numpy as np
import cv2

W, H = 1024, 600
DEV = int(sys.argv[1]) if len(sys.argv) > 1 else 1
N = int(sys.argv[2]) if len(sys.argv) > 2 else 100
CW = int(sys.argv[3]) if len(sys.argv) > 3 else 0
CH = int(sys.argv[4]) if len(sys.argv) > 4 else 0

cap = cv2.VideoCapture(DEV)
if CW and CH:
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CW)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CH)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
print("采集尺寸 %.0fx%.0f  格式 %.0f  fps设定 %.1f"
      % (cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT),
         cap.get(cv2.CAP_PROP_FOURCC), cap.get(cv2.CAP_PROP_FPS)))
ok, f0 = cap.read()
if not ok:
    raise SystemExit("读帧失败")
print("实到帧 %s" % (f0.shape,))

from icraft import xrt
dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
chunk = dev.getMemRegion("udma").malloc(W * H * 2, False)

t = [0.0, 0.0, 0.0, 0.0]
for i in range(N):
    t0 = time.time(); ok, frame = cap.read();            t[0] += time.time() - t0
    if not ok:
        continue
    t0 = time.time()
    fh, fw = frame.shape[:2]
    s = min(W / float(fw), H / float(fh))
    nw, nh = max(1, int(fw * s)), max(1, int(fh * s))
    r = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
    canvas = np.zeros((H, W, 3), np.uint8)
    canvas[(H - nh) // 2:(H - nh) // 2 + nh, (W - nw) // 2:(W - nw) // 2 + nw] = r
    t[1] += time.time() - t0
    t0 = time.time()
    a = canvas
    raw = (((a[:, :, 0].astype(np.uint16) >> 3) << 11)
           | ((a[:, :, 1].astype(np.uint16) >> 2) << 5)
           | (a[:, :, 2].astype(np.uint16) >> 3)).astype(np.uint16).tobytes()
    t[2] += time.time() - t0
    t0 = time.time(); chunk.write(0, raw, len(raw));      t[3] += time.time() - t0

cap.release()
tot = sum(t)
print("-" * 58)
print("  %-22s %9s %8s" % ("阶段", "总耗时s", "每帧ms"))
for nm, v in zip(("① cap.read() 取帧+解码", "② letterbox 缩放合成",
                  "③ RGB565 转换打包", "④ udma 写入(PS DDR)"), t):
    print("  %-22s %9.3f %8.2f" % (nm, v, v / N * 1000))
print("  %-22s %9.3f %8.2f" % ("合计", tot, tot / N * 1000))
print("  ⇒ 上限 %.2f fps（不含任何优化）" % (N / tot))
print("PROF_DONE")
