# -*- coding: utf-8 -*-
"""生成板端 S1 的输入张量（与 board_e2e.py 的预处理逐行一致），供板端全链路使用。

board_e2e.py:256-260
    im = Image.open(png).convert("RGB"); w,h = im.size
    x0=(i*37)%max(1,w-S); y0=(i*53)%max(1,h-S)
    px = asarray(im.crop((x0,y0,x0+S,y0+S)), float32)/127.5 - 1.0
    x  = from_numpy(px.transpose(2,0,1)).unsqueeze(0)
    nhwc(x) -> (1,256,256,3) 写进 in0.ftmp
"""
import os
import numpy as np
from PIL import Image

PNG_DIR = "/mnt/e/fudanwei/工作区/testset/kodak_real"
OUT = "/mnt/e/fudanwei/工作区/_board_run/e2e_inputs"
S = 256

os.makedirs(OUT, exist_ok=True)
pngs = sorted(f for f in os.listdir(PNG_DIR) if f.lower().endswith(".png"))
print("数据集 %d 张，前几张: %s" % (len(pngs), pngs[:4]))

for i in range(4):
    png = pngs[i % len(pngs)]
    im = Image.open(os.path.join(PNG_DIR, png)).convert("RGB")
    w, h = im.size
    x0, y0 = (i * 37) % max(1, w - S), (i * 53) % max(1, h - S)
    px = np.asarray(im.crop((x0, y0, x0 + S, y0 + S)), dtype=np.float32) / 127.5 - 1.0
    x = np.ascontiguousarray(px.transpose(2, 0, 1)[None])       # NCHW
    x_nhwc = np.ascontiguousarray(x.transpose(0, 2, 3, 1))      # NHWC = in0.ftmp
    p = os.path.join(OUT, "s%d_in0.ftmp" % i)
    x_nhwc.astype(np.float32).tofile(p)
    print("  s%d: %s crop=(%d,%d)+%d  -> %s (%d B) range [%.4f, %.4f]"
          % (i, png, x0, y0, S, p, x_nhwc.nbytes,
             float(x_nhwc.min()), float(x_nhwc.max())))
