# -*- coding: utf-8 -*-
r"""Build a binary (float32) calibration set for Icraft INT8 quantization.

Icraft reads calibration binaries as raw float32 (NHWC layout matching the
parsed network input).  We crop 256x256 patches from the Kodak test set,
scale to [-1,1] (the same normalisation the GLC reference pipeline uses)
and dump them as .ftmp plus a forward_list file.

Usage:
  python hb_make_calib.py --src <kodak dir> --out <calib dir> [--n 8]
                          [--size 256] [--listname calib_list.txt]
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=r"E:\fudanwei\工作区\testset\kodak")
    ap.add_argument("--out", default=r"E:\fudanwei\工作区\hostcheck\calib")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--listname", default="calib_list.txt")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    pngs = sorted(f for f in os.listdir(a.src) if f.lower().endswith(".png"))
    if not pngs:
        print("no PNGs under " + a.src)
        return 1

    names = []
    for i in range(a.n):
        p = os.path.join(a.src, pngs[i % len(pngs)])
        im = Image.open(p).convert("RGB")
        w, h = im.size
        s = a.size
        # deterministic crop window that walks across the image
        x = (i * 37) % max(1, w - s)
        y = (i * 53) % max(1, h - s)
        im = im.crop((x, y, x + s, y + s))
        arr = np.asarray(im, dtype=np.float32) / 127.5 - 1.0     # [-1,1]
        arr = np.ascontiguousarray(arr)                          # NHWC
        fn = "cal_%02d.ftmp" % i
        arr.tofile(os.path.join(a.out, fn))
        names.append(fn)
        print("  %s  <- %s crop(%d,%d)  shape=%s  min=%.3f max=%.3f"
              % (fn, pngs[i % len(pngs)], x, y, arr.shape, arr.min(), arr.max()))

    lst = os.path.join(a.out, a.listname)
    with open(lst, "w", encoding="utf-8") as f:
        f.write("\n".join(names) + "\n")
    print("wrote %s (%d entries)" % (lst, len(names)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
