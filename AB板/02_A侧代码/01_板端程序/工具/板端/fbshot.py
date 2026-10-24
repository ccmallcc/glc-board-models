#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把屏上现在显示的东西抓成一张小 JPEG（走串口也能拉回来的尺寸）。

★ 板上**没有 /dev/fb0** —— 这块屏不是 Linux framebuffer，而是
  **PL 里的显示引擎从 DDR 里读**：`glc_ui.py` 把 RGB565 画布写进 DDR，
  再通过寄存器 `0x40080054`（DISPLAY_READ_ADDR）告诉 PL "从哪读"。
  所以截图 = 读那个寄存器拿到地址，再用 /dev/mem 把那块 1024×600×2 B 读出来。

用法: python3 /root/fbshot.py [输出路径] [--scale 0.5] [--q 55]
"""
import mmap
import os
import struct
import sys

import numpy as np
from PIL import Image

W, H = 1024, 600
REG_BASE = 0x40080000
REG_LEN = 0x1000
DISPLAY_READ_ADDR = 0x40080054


def read_reg():
    fd = os.open('/dev/mem', os.O_RDONLY | os.O_SYNC)
    try:
        mm = mmap.mmap(fd, REG_LEN, mmap.MAP_SHARED, mmap.PROT_READ, offset=REG_BASE)
        try:
            return struct.unpack_from('<I', mm, DISPLAY_READ_ADDR - REG_BASE)[0]
        finally:
            mm.close()
    finally:
        os.close(fd)


def grab(addr, nbytes):
    fd = os.open('/dev/mem', os.O_RDONLY | os.O_SYNC)
    try:
        mm = mmap.mmap(fd, nbytes, mmap.MAP_SHARED, mmap.PROT_READ, offset=addr)
        try:
            return mm.read(nbytes)
        finally:
            mm.close()
    finally:
        os.close(fd)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    out = args[0] if args else '/root/_shot.jpg'
    scale, q = 0.5, 55
    for i, a in enumerate(sys.argv):
        if a == '--scale':
            scale = float(sys.argv[i + 1])
        if a == '--q':
            q = int(sys.argv[i + 1])

    addr = read_reg()
    print('FBSHOT_ADDR 0x%08x' % addr)
    if addr < 0x100000 or addr % 2:
        print('FBSHOT_FAIL 显示地址看着不对（0x%08x），可能屏没开' % addr)
        return 2
    n = W * H * 2
    raw = grab(addr, n)
    if len(raw) < n:
        print('FBSHOT_FAIL 只读到 %d B（要 %d）' % (len(raw), n))
        return 2
    a = np.frombuffer(raw, dtype=np.uint16).reshape(H, W)
    r = ((a >> 11) & 0x1F).astype(np.uint16) * 255 // 31
    g = ((a >> 5) & 0x3F).astype(np.uint16) * 255 // 63
    b = (a & 0x1F).astype(np.uint16) * 255 // 31
    im = Image.fromarray(np.stack([r, g, b], -1).astype(np.uint8))
    if scale != 1.0:
        im = im.resize((int(W * scale), int(H * scale)), Image.LANCZOS)
    im.save(out, quality=q, optimize=True)
    print('FBSHOT_OK %s %d %s' % (out, os.path.getsize(out), im.size))
    return 0


if __name__ == '__main__':
    sys.exit(main())
