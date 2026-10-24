#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""cam_to_hdmi.py —— USB 摄像头 → PL DDR 帧缓冲 → HDMI 显示（1024×600）【v2 修正版】

架构（全程走 PS，**不吃 PL 资源**）：
    USB 摄像头 --UVC--> /dev/video1 --V4L2/cv2--> numpy 帧
        --> 缩放/居中到 1024×600 --> RGB565
        --> 写进 PL 的 udma 保留内存 --> 写 0x40080054 = 地址>>3 --> HDMI 出图

★★ 2026-10-14 修了一个**我自己引入的颜色 bug** ★★
   cv2 读出来的是 **BGR**，而 `hdmi-show-1024x600.py::to_rgb565()` 是按 **RGB** 写的
   （它喂的是 PIL 的 `.convert("RGB")`）。把 cv2 的 BGR 直接喂进去 ⇒ **红蓝互换**。
   实测（纯色 64x64，期望 红=0xF800 绿=0x07E0 蓝=0x001F）：

       输入(cv2 BGR)      A:通道0置高     B:通道2置高     C:cv2.COLOR_BGR2BGR565
       纯红 (0,0,255)     0x001F ✗        0xF800 ✓        0x0000 ✗
       纯绿 (0,255,0)     0x07E0 ✓        0x07E0 ✓        0x00E0 ✗
       纯蓝 (255,0,0)     0xF800 ✗        0x001F ✓        0x001F ✓

   ⇒ **只有写法 B（通道 2 置高位）三色全对**。
   ⇒ 注意 **`cv2.COLOR_BGR2BGR565` 不能用**（纯红给 0x0000，纯绿给 0x00E0，都不对）。

性能（实测，板子 A9 @ ~1GHz）：
    · udma 写入         0.92 ms  ← 完全不是瓶颈（1.34 GB/s）
    · cap.read()  取帧  ~30-37 ms ← 受相机 30fps 限制（640x480 MJPG）
    · RGB565 转换       ~28 ms（本版已把 3 次 astype 并成 1 次）
    · 缩放/合成         ~3-10 ms（--no-scale 可省）
    ⇒ 端到端约 15~25 fps，天花板是相机自身的 30fps。

用法：
    python3 cam_to_hdmi.py --list
    python3 cam_to_hdmi.py --dev 1 --probe             # 抓一帧存 PNG
    python3 cam_to_hdmi.py --dev 1 --frames 300        # 上屏
    python3 cam_to_hdmi.py --dev 1 --no-scale          # 1:1 居中（省缩放）
"""
import argparse
import os
import sys
import time

import numpy as np

W, H = 1024, 600
BUF = W * H * 2
DISPLAY_READ_ADDR = 0x40080054
VTC_ENABLE = 0x400800B4
DEV_URL = "axi://zg330aiu?npu=0x40000000&dma=0x80000000"


def to_rgb565_bgr(bgr):
    """cv2 的 BGR -> RGB565（R 在 bit11-15）。★ 通道 2 才是 R，别搞反。"""
    a = bgr.astype(np.uint16)                      # 只做一次 astype
    return (((a[:, :, 2] >> 3) << 11)
            | ((a[:, :, 1] >> 2) << 5)
            | (a[:, :, 0] >> 3)).astype(np.uint16)


def letterbox(frame, canvas, scale=True):
    """把 frame 贴进 canvas 中央；scale=True 等比缩放，False 则 1:1 居中（超出裁剪）"""
    import cv2
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


def list_devices():
    import glob
    print("=== 系统里的 video 设备 ===")
    for p in sorted(glob.glob("/dev/video*")):
        nm = ""
        try:
            nm = open("/sys/class/video4linux/%s/name" % os.path.basename(p)).read().strip()
        except OSError:
            pass
        print("  %-14s %s" % (p, nm))
    print("\n`mvx` 是 SoC 平台自带视频子系统，不是 USB 摄像头。")


def open_cam(dev_id, cw=0, ch=0):
    import cv2
    cap = cv2.VideoCapture(dev_id)
    if not cap.isOpened():
        raise SystemExit("/dev/video%d 打不开；用 --list 看设备号" % dev_id)
    if cw and ch:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, cw)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, ch)
    return cap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", type=int, default=1)
    ap.add_argument("--frames", type=int, default=300)
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--no-scale", dest="scale", action="store_false")
    ap.add_argument("--size", default="", help="采集尺寸 如 640x480")
    ap.add_argument("--out", default="/root/cam_probe.png")
    ap.set_defaults(scale=True)
    a = ap.parse_args()

    if a.list:
        list_devices()
        return

    import cv2

    cw = ch = 0
    if a.size:
        cw, ch = (int(x) for x in a.size.lower().split("x"))
    cap = open_cam(a.dev, cw, ch)
    print("  摄像头 /dev/video%d  %.0fx%.0f @ %.1f fps  缩放=%s"
          % (a.dev, cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT),
             cap.get(cv2.CAP_PROP_FPS), a.scale))

    if a.probe:
        import cv2
        ok, frame = cap.read()
        cap.release()
        if not ok:
            raise SystemExit("读帧失败")
        print("  抓到一帧: %s  min=%d max=%d mean=%.1f" % (frame.shape, frame.min(),
                                                          frame.max(), frame.mean()))
        cv2.imwrite(a.out, frame)
        print("  已存 %s" % a.out)
        return

    from icraft import xrt
    dev = xrt.Device.Open(DEV_URL)
    reg = dev.defaultRegRegion()
    chunk = dev.getMemRegion("udma").malloc(BUF, False)
    addr = chunk.begin.addr()
    reg.write(VTC_ENABLE, 1)
    reg.write(0x40080018, 1)
    reg.write(DISPLAY_READ_ADDR, addr >> 3)
    print("  udma addr=0x%08x -> 0x40080054=0x%08x ; VTC=1 显示使能=1" % (addr, addr >> 3))

    canvas = np.zeros((H, W, 3), np.uint8)      # 复用，不每帧新建
    n_ok, t_conv, t_read, t_write, t_bytes = 0, 0.0, 0.0, 0.0, 0.0
    t0 = time.time()
    t_last = t0
    for i in range(a.frames):
        tr = time.time()
        ok, frame = cap.read()
        t_read += time.time() - tr
        if not ok:
            time.sleep(0.03)
            continue
        tc = time.time()
        arr = to_rgb565_bgr(letterbox(frame, canvas, a.scale))
        tb = time.time(); raw = arr.tobytes(); t_bytes += time.time() - tb
        tw = time.time(); chunk.write(0, raw, len(raw)); t_write += time.time() - tw
        t_conv += time.time() - tc
        n_ok += 1
        if n_ok % 30 == 0:
            now = time.time()
            print("  已上屏 %d 帧, %.1f fps | 取帧 %.1f 转换 %.1f tobytes %.1f 写入 %.1f ms"
                  % (n_ok, 30.0 / max(now - t_last, 1e-6), t_read / n_ok * 1000,
                     (t_conv - t_bytes) / n_ok * 1000, t_bytes / n_ok * 1000,
                     t_write / n_ok * 1000), flush=True)
            t_last = now
    cap.release()
    dt = time.time() - t0
    print("完成: %d 帧 / %.1f s = %.2f fps" % (n_ok, dt, n_ok / max(dt, 1e-6)))
    print("  分段(每帧 ms): 取帧 %.1f  转换 %.1f  tobytes %.1f  写入 %.1f  = 已计 %.1f"
          % (t_read / n_ok * 1000, (t_conv - t_bytes) / n_ok * 1000, t_bytes / n_ok * 1000,
             t_write / n_ok * 1000, (t_read + t_conv + t_write) / n_ok * 1000))
    print("  实际墙钟 %.1f ms/帧 ⇒ 未归类 %.1f ms/帧"
          % (dt / n_ok * 1000, (dt - t_read - t_conv - t_write) / n_ok * 1000))
    print("CAM_DONE")


if __name__ == "__main__":
    main()
