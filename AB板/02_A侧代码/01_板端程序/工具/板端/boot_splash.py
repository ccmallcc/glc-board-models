#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""开机进度条：在 UI 起来之前，别让屏全黑。

## 为什么需要它
现在的开机链是：位流加载 → **立刻拉掉 HDMI 同步（黑屏，防花屏）** → 加速环境 → 起 UI。
从拉黑到 UI 出第一帧大约 **13~22 s**，这段时间屏是全黑的 —— 现场看就是"板子没起来"。

## 它怎么画上去的（这条是关键，别自己发明）
- 板子**没有 /dev/fb0**：屏是 PL 从 DDR 里读，读哪由寄存器 `0x40080054` 决定；
- `/dev/udmabuf0` 是一块 **128 MB 的物理连续保留区**（phys `0x30100000`），
  glc_ui.py 的显示缓冲就在这一类区域里；
- 所以：mmap udmabuf0 → 画图 → 把 `0x40080054` 指过去 → 打开显示。
  寄存器经 `/dev/mem` 写 **是允许的**（设备区），而读 DDR 会被 STRICT_DEVMEM 挡（实测 EPERM），
  两者别混。

## 用法
    python3 boot_splash.py --pct 10 --text "加载位流"
    python3 boot_splash.py --pct 45 --text "预热加速环境"
    python3 boot_splash.py --pct 90 --text "启动界面"

⚠️ 只在 **UI 起来之前** 用。UI 一旦开始自己的显示，就不要再调它（会抢同一块屏）。
"""
import argparse
import mmap
import os
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 1024, 600
UDMA = '/dev/udmabuf0'
UDMA_PHYS = 0x30100000          # 见 /sys/class/u-dma-buf/udmabuf0/phys_addr
REG_BASE, REG_LEN = 0x40080000, 0x1000
R_DISPLAY_ADDR = 0x40080054     # 显示引擎从哪读
R_DISPLAY_EN = 0x40080018
R_VTC_ENABLE = 0x400800B4    # ★ 视频源选 DDR 帧缓冲；不写这个 ⇒ 看到的是悬空 cam_* ⇒ 花屏
R_HDMI_DISABLE = 0x40080078

BG = (16, 18, 22)
FG = (240, 240, 240)
DIM = (120, 126, 136)
ACC = (64, 200, 120)


def font(sz):
    for p in ('/root/ui_font.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, sz)
            except OSError:
                pass
    return ImageFont.load_default()


def draw(pct, text, sub=''):
    im = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(im)
    d.text((W // 2, 150), 'GLC 正在启动', font=font(46), fill=FG, anchor='mm')
    d.text((W // 2, 210), sub or '请稍候', font=font(24), fill=DIM, anchor='mm')
    x0, x1, y0, y1 = 160, W - 160, 300, 340
    d.rounded_rectangle((x0, y0, x1, y1), radius=10, outline=DIM, width=2)
    if pct > 0:
        w = int((x1 - x0 - 8) * min(max(pct, 0), 100) / 100.0)
        d.rounded_rectangle((x0 + 4, y0 + 4, x0 + 4 + w, y1 - 4), radius=7, fill=ACC)
    d.text((W // 2, 380), '%d%%   %s' % (pct, text), font=font(30), fill=FG, anchor='mm')
    return im


def to565(im):
    a = np.asarray(im.convert('RGB'), dtype=np.uint16)
    return (((a[:, :, 0] >> 3) << 11) | ((a[:, :, 1] >> 2) << 5) | (a[:, :, 2] >> 3)).astype(np.uint16)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pct', type=int, default=10)
    ap.add_argument('--text', default='')
    ap.add_argument('--sub', default='')
    ap.add_argument('--hold', type=float, default=0.0, help='画完后等这么多秒（默认不等）')
    a = ap.parse_args()

    raw = to565(draw(a.pct, a.text, a.sub)).tobytes()
    assert len(raw) == W * H * 2, len(raw)

    # ★ 2026-10-23 关键修正：**不能用 mmap 写**。
    #   udmabuf 的 mmap 是 cacheable 的，`mm.flush()` 又返回 EINVAL（不支持 msync），
    #   于是数据可能一直留在 CPU cache 里没落到 DRAM ⇒ PL 读到的是旧/垃圾内容 ⇒ **花屏**。
    #   改成 pwrite 走内核：驱动用的是 coherent DMA 内存，写完立刻对 PL 可见。
    fd = os.open(UDMA, os.O_RDWR | os.O_SYNC)
    try:
        off = 0
        while off < len(raw):
            off += os.pwrite(fd, raw[off:], off)
    finally:
        os.close(fd)

    fd = os.open('/dev/mem', os.O_RDWR | os.O_SYNC)
    try:
        reg = mmap.mmap(fd, REG_LEN, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=REG_BASE)
        try:
            # ★★ 顺序与**单位**都跟 glc_ui.disp_enable() 一模一样（这是花屏的真因）：
            #   ① HDMI_DISABLE=0 先放开同步 ② VTC_ENABLE=1 ③ DISPLAY_ENABLE=1
            #   ④ 帧地址写的是 **addr >> 3**（寄存器按 8 字节为单位！我之前写的是全地址）
            struct.pack_into('<I', reg, R_HDMI_DISABLE - REG_BASE, 0)
            struct.pack_into('<I', reg, R_VTC_ENABLE - REG_BASE, 1)
            struct.pack_into('<I', reg, R_DISPLAY_EN - REG_BASE, 1)
            struct.pack_into('<I', reg, R_DISPLAY_ADDR - REG_BASE, UDMA_PHYS >> 3)
        finally:
            reg.close()
    finally:
        os.close(fd)

    print('SPLASH_OK pct=%d text=%s' % (a.pct, a.text))
    if a.hold > 0:
        import time
        time.sleep(a.hold)
    return 0


if __name__ == '__main__':
    sys.exit(main())
