#!/usr/bin/env python3
# ============================================================================
# GLC 2026-10-14：本文件 = hdmi-show-1280x800.py 的副本（V8 那一版），
#   正文一字未动（寄存器写入序列完全相同），只改了一处：
#       W, H = 1280, 800   ->   W, H = 1024, 600
#   改动理由：**屏换了**。V9 位流的 raster 是 **1024x600@50.000MHz**
#       （color_bar.v 的 VIDEO_1024_600 组 + rx_sdi.v 里 50MHz 像素时钟 PLL），
#       而 PS 侧写进 DDR 的帧必须与 raster 同尺寸：
#           RGB565 1024*600*2 = **1,228,800 B**
#           = RTL 里 FRAME_READ_LEN = 1024*600*16/64 = **153,600** 个 64bit 字。
#       写 1280x800 或 1920x1080 的帧，屏上只会显示左上角那一块 1024x600。
#
#   新屏是 **DWE2100**，参数逐字段来自它自己的 EDID（256B，校验和 0xF9/0xD0 均通过）：
#       原生 1024x600@59.821Hz，PCLK 标称 50.250MHz，H 1024/44/88/188(1344)，
#       V 600/3/6/16(625)，**HSync+ / VSync-**（旧屏 MPI107 是两个都正）。
#       板上 PLLE2 只有整数分频，实际产生 50.000MHz（-0.498%）⇒ 59.524Hz。
#       详见 GLC-共享包 59 号文档与 工具/hdmi/hdmi_1024x600_timing.vh。
#
#   ⚠️ 未经上板验证（写这份时 V9 位流还在综合）。寄存器序列一字未动。
# ============================================================================
# -*- coding: utf-8 -*-
"""
hdmi-show.py —— HDMI 显图（严格照官方最小序列）

官方依据（fpai_demo_package_26040701.zip）：
  deps/modelzoo_utils/include/et_device.hpp
      inline void enableCameraVTC(icraft::xrt::Device &device, int enable = 1)
      {
          // by default, switch off VTC using real sdi camera input
          device.defaultRegRegion().write(0x40080000 + 0xB4, enable); // VTC_enable = 1; VTC_disable = 0
      }
  deps/modelzoo_utils/include/pipeline/io/output/hdmi_display.hpp
      const static auto DISPLAY_READ_ADDR = 0x40080054;
      display_chunk_ = device_.getMemRegion("udma").malloc(w*h*2, false);
      void show(int8_t *frame_data) const {
          display_chunk_.write(0, (char *)frame_data, buffer_size_);
          device_.defaultRegRegion().write(DISPLAY_READ_ADDR, display_chunk_->begin.addr() >> 3);
      }

寄存器语义（官方 et_device.hpp）：
  +0x04 摄像头 take 地址      +0x18 PL hard-resize 使能（显示时不要写！）
  +0x50 摄像头 write 地址     +0x54 显示帧地址           +0x58 摄像头 done
  +0x6C 帧字节数              +0xB4 VTC 使能（无摄像头必须置 1）

用法:
  python3 hdmi-show.py --pattern bars        # 默认：开 VTC + 官方 udma 缓冲 + 只写 0x40080054
  python3 hdmi-show.py --image /root/x.png
  python3 hdmi-show.py --pattern bars --no-vtc       # 不开 VTC（对照）
  python3 hdmi-show.py --pattern bars --ps-udmabuf   # 对照：直接写 PS 侧 /dev/udmabuf0
  python3 hdmi-show.py --pattern bars --extra        # 对照：额外写队友那几个寄存器
"""
import argparse
import os

import numpy as np
from PIL import Image

W, H = 1024, 600
BUF = W * H * 2
DISPLAY_READ_ADDR = 0x40080054
VTC_ENABLE = 0x400800B4
# 官方语义：0x18 = PL hard-resize 使能；0x50 = 摄像头 write 地址  => 显示静态图时都不该写
EXTRA_REGS = [(0x40080018, 1), (0x40080068, 0x11)]


def to_rgb565(a):
    r = (a[:, :, 0].astype(np.uint16) >> 3) << 11
    g = (a[:, :, 1].astype(np.uint16) >> 2) << 5
    b = (a[:, :, 2].astype(np.uint16) >> 3)
    return (r | g | b).astype(np.uint16)


def frame_bars():
    a = np.zeros((H, W, 3), np.uint8)
    cols = [(255, 255, 255), (255, 255, 0), (0, 255, 255), (0, 255, 0),
            (255, 0, 255), (255, 0, 0), (0, 0, 255), (32, 32, 32)]
    bw = W // len(cols)
    for i, c in enumerate(cols):
        a[:, i * bw:(i + 1) * bw] = c
    return a


def frame_solid(c):
    a = np.zeros((H, W, 3), np.uint8)
    a[:, :] = c
    return a


def frame_image(path):
    im = Image.open(path).convert("RGB")
    im.thumbnail((W, H), Image.LANCZOS)
    canvas = Image.new("RGB", (W, H), (0, 0, 0))
    canvas.paste(im, ((W - im.width) // 2, (H - im.height) // 2))
    print("[HDMI] image %dx%d -> centered on %dx%d black" % (im.width, im.height, W, H))
    return np.array(canvas)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default="")
    ap.add_argument("--pattern", default="bars",
                    choices=["bars", "red", "green", "blue", "white", "black"])
    ap.add_argument("--no-vtc", action="store_true")
    ap.add_argument("--ps-udmabuf", action="store_true")
    ap.add_argument("--extra", action="store_true")
    a = ap.parse_args()

    if a.image:
        frame = frame_image(a.image)
    elif a.pattern in ("red", "green", "blue", "white", "black"):
        frame = frame_solid({"red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255),
                             "white": (255, 255, 255), "black": (0, 0, 0)}[a.pattern])
    else:
        frame = frame_bars()
    raw = to_rgb565(frame).tobytes()
    print("[HDMI] frame bytes = %d (expect %d)" % (len(raw), BUF))

    from icraft import xrt
    dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
    reg = dev.defaultRegRegion()

    if a.ps_udmabuf:
        sysdir = "/sys/class/u-dma-buf/udmabuf0"
        with open(os.path.join(sysdir, "phys_addr")) as f:
            phys = int(f.read().strip(), 0)
        with open("/dev/udmabuf0", "r+b") as f:
            f.seek(0)
            f.write(raw)
            f.flush()
        for n, v in (("sync_offset", "0"), ("sync_size", str(len(raw))),
                     ("sync_direction", "1"), ("sync_for_device", "1")):
            with open(os.path.join(sysdir, n), "w") as f:
                f.write(v)
        target = phys >> 3
        print("[HDMI] path=PS udmabuf phys=0x%08x -> 0x%08x" % (phys, target))
    else:
        chunk = dev.getMemRegion("udma").malloc(BUF, False)
        addr = chunk.begin.addr()
        chunk.write(0, raw, len(raw))
        target = addr >> 3
        print("[HDMI] path=official udma chunk addr=0x%08x -> 0x%08x" % (addr, target))

    if not a.no_vtc:
        reg.write(VTC_ENABLE, 1)
        print("[HDMI] enableCameraVTC: 0x%08x = 1" % VTC_ENABLE)
        reg.write(0x40080018, 1)          # 官方 sdicamera_input_actor 注释：0x18 = 是否使能 HDMI 显示
        print("[HDMI] 0x40080018 = 1  <-- 使能 HDMI 显示")

    if a.extra:
        for off, val in EXTRA_REGS:
            reg.write(off, val)
            print("[HDMI] (extra) 0x%08x = %d" % (off, val))
        reg.write(0x40080050, target)
        print("[HDMI] (extra) 0x40080050 = 0x%08x" % target)

    reg.write(DISPLAY_READ_ADDR, target)
    print("[HDMI] wrote 0x40080054 = 0x%08x   DONE" % target)


if __name__ == "__main__":
    main()
