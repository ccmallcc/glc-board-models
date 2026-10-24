#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""prof_cam3.py —— 把"一帧从相机到屏"的开销**逐段拆开**，看哪一段是 PL 能接手的

背景：glc_ui.py 实测 ~43 ms/帧，但只有拆开才知道：
  · cap.read() 里有多少是 USB+相机（PL 一定碰不到，USB 控制器在 PS 侧 DWC OTG）
  · 有多少是 MJPG 解码（PL 可以接，但要一个 JPEG 解码器）
  · RGB565/缩放/合成 各占多少（PL 最适合接的就是这段）

手法：OpenCV 的 V4L2 后端里
  grab()    = 从驱动拿一帧缓冲        -> 相机 + USB + 驱动
  retrieve()= 把 MJPG 解成 BGR 矩阵    -> JPEG 解码
所以 grab 和 read 的差就是解码时间。
"""
import time

import cv2
import numpy as np

DEV = 1
N = 60
W, H = 1024, 600
PW, PH = 610, 458


def bench(label, fn, n=N):
    fn()                                   # 预热
    t0 = time.time()
    for _ in range(n):
        fn()
    dt = (time.time() - t0) / n * 1000.0
    print("  %-34s %8.2f ms" % (label, dt))
    return dt


def main():
    cap = cv2.VideoCapture(DEV)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    for _ in range(8):
        cap.read()
    print("  相机 %.0fx%.0f  标称 %.0f fps  实际 %.1f fps"
          % (cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT),
             cap.get(cv2.CAP_PROP_FPS), cap.get(cv2.CAP_PROP_FPS)))

    print("\n=== A. 取帧分解（决定天花板的是这段，PL 基本插不上手）===")
    tg = bench("cap.grab()   相机+USB+驱动", lambda: cap.grab())
    tr = bench("cap.read()   grab+解码 一起", lambda: cap.read())
    print("  ⇒ 其中 MJPG 解码 ≈ %.2f ms，相机+USB ≈ %.2f ms" % (tr - tg, tg))

    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise SystemExit("抓不到帧")
    print("  帧 %s  均值 %.1f" % (frame.shape, frame.mean()))

    print("\n=== B. 像素处理分解（这段是 PL 真正能接的）===")
    canvas = np.zeros((H, W, 3), np.uint8)
    u16 = np.zeros((H, W), np.uint16)

    def do_resize():
        cv2.resize(frame, (PW, PH), interpolation=cv2.INTER_AREA)

    def do_lut():
        cv2.LUT(frame, np.arange(256, dtype=np.uint8))

    def do_conv_full():
        s = canvas
        a = s.astype(np.uint16)
        u16[:, :] = (((a[:, :, 2] >> 3) << 11) | ((a[:, :, 1] >> 2) << 5) | (a[:, :, 0] >> 3))

    small = canvas[46:504, 207:817]

    def do_conv_rect():
        a = small.astype(np.uint16)
        u16[46:504, 207:817] = (((a[:, :, 2] >> 3) << 11) | ((a[:, :, 1] >> 2) << 5)
                                | (a[:, :, 0] >> 3))

    t_resize = bench("cv2.resize 640x480 -> 610x458", do_resize)
    t_lut = bench("cv2.LUT 曝光 (640x480)", do_lut)
    t_full = bench("RGB565 全屏 1024x600 (614400 px)", do_conv_full, 30)
    t_rect = bench("RGB565 预览矩形 (279380 px)", do_conv_rect, 30)
    raw = u16.tobytes()
    bench("u16.tobytes() 1.2MB", lambda: u16.tobytes(), 30)

    print("\n=== C. 折算：如果这些搬到 PL ===")
    print("  像素吞吐参考: 1024x600 = 614400 px/帧")
    for clk in (100e6, 150e6, 200e6, 250e6):
        print("     PL @ %5.0f MHz 1px/clk -> 一帧全部像素 %6.2f ms"
              % (clk / 1e6, 614400 / clk * 1000))
    print("  PS 侧 像素处理合计 ≈ %.2f ms（resize %.2f + 曝光 %.2f + RGB565 %.2f）"
          % (t_resize + t_lut + t_rect, t_resize, t_lut, t_rect))
    print("  一帧总墙钟 ≈ %.2f ms  ⇒ 其中 PL 有可能接手的上限 = %.1f%%"
          % (tr + t_resize + t_lut + t_rect, (t_resize + t_lut + t_rect) / (tr + t_resize + t_lut + t_rect) * 100))
    print("\nPROF3_DONE")


if __name__ == "__main__":
    main()
