#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""实测：把一张大图变成模型输入 (1,256,256,3) float32 要多久，各部分各占多少。

这决定了"预处理要不要搬到 FPGA"这个问题值不值得做。
用板上真实的图跑（t1 是 2364x1773，最大的那张）。
"""
import os
import sys
import time

import numpy as np
from PIL import Image


def T(tag, fn, n=3):
    ts = []
    r = None
    for _ in range(n):
        t0 = time.time()
        r = fn()
        ts.append(time.time() - t0)
    ts.sort()
    print('  %-52s %8.2f ms' % (tag, ts[len(ts) // 2] * 1000))
    return r


IMGS = [('/root/photo_t/t1_tree.jpg', 'fit'),
        ('/root/photo_t/t2_person.jpg', 'fit'),
        ('/root/photo_t/t3_cartoon.jpg', 'fit'),
        ('/root/photo_t/t4_concert.jpg', 'fit')]

for path, mode in IMGS:
    if not os.path.exists(path):
        print('  缺 %s' % path)
        continue
    w0, h0 = Image.open(path).size
    sz = os.path.getsize(path)
    print('=' * 78)
    print('%s   %dx%d  %.0f KB   px=%.2f M' % (os.path.basename(path), w0, h0, sz / 1024, w0 * h0 / 1e6))
    print('=' * 78)

    T('① Image.open() 只读头（不解码像素）', lambda: Image.open(path).size)

    def full_decode():
        return Image.open(path).convert('RGB')
    im = T('② open + convert("RGB")  ★真正的 JPEG 解码', full_decode)

    s = 256.0 / min(w0, h0)
    nw, nh = max(256, int(round(w0 * s))), max(256, int(round(h0 * s)))
    print('      缩放后 %dx%d' % (nw, nh))

    T('③ resize LANCZOS  ★重采样（目前用的）', lambda: im.resize((nw, nh), Image.LANCZOS))
    T('④ resize BILINEAR（对照，更快但更糙）', lambda: im.resize((nw, nh), Image.BILINEAR))
    T('⑤ resize BOX（对照，纯平均，最快）', lambda: im.resize((nw, nh), Image.BOX))

    rim = im.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - 256) // 2, (nh - 256) // 2
    T('⑥ crop 居中 256x256', lambda: rim.crop((left, top, left + 256, top + 256)))
    cim = rim.crop((left, top, left + 256, top + 256))

    T('⑦ np.asarray + /127.5-1 归一化', lambda: (np.asarray(cim, dtype=np.float32) / 127.5 - 1.0))
    arr = (np.asarray(cim, dtype=np.float32) / 127.5 - 1.0)[None, ...]
    T('⑧ tofile 写 786432 B 到 tmpfs', lambda: arr.astype(np.float32).tofile('/dev/shm/_p.wav'))

    # 整条链
    def whole():
        i = Image.open(path).convert('RGB')
        w, h = i.size
        sc = 256.0 / min(w, h)
        nw2, nh2 = max(256, int(round(w * sc))), max(256, int(round(h * sc)))
        i = i.resize((nw2, nh2), Image.LANCZOS)
        l, t = (nw2 - 256) // 2, (nh2 - 256) // 2
        i = i.crop((l, t, l + 256, t + 256))
        a = (np.asarray(i, dtype=np.float32) / 127.5 - 1.0)[None, ...]
        a.tofile('/dev/shm/_p.wav')
        return a
    T('★ 整条预处理链（当前做法）', whole)
    print()

print('=' * 78)
print('对照：编码一张图现在只要 ~600 ms（引擎载入后）')
print('=' * 78)
print('PREP_BENCH_DONE')
