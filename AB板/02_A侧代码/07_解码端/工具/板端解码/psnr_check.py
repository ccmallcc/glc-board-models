#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""psnr_check.py —— 从 decode_board.py 的 npz 里算 PSNR

  x_hat  : decode_board.py 输出，NCHW (1,3,256,256)，范围 [-1,1]
  参考   : /root/glc/inputs_photo/pN.ftmp，NHWC (1,256,256,3)，范围 [-1,1]
           （这就是 enc_image.py 送进编码器的 256x256 中心裁剪，**与编码输入完全同源**）

PSNR 口径与 glc_board_full.py 的 psnr() 一致：mse 在 [-1,1] 尺度上算，10*log10(4/mse)
（4.0 = (max-min)^2 = 2^2）

用法: python3 psnr_check.py <out.npz> <ref.ftmp> [标签]
"""
import sys

import numpy as np


def main():
    if len(sys.argv) < 3:
        print("用法: psnr_check.py <out.npz> <ref.ftmp> [标签]")
        sys.exit(2)
    npz_p, ref_p = sys.argv[1], sys.argv[2]
    tag = sys.argv[3] if len(sys.argv) > 3 else ''

    d = np.load(npz_p)
    if 'x_hat' not in d:
        print("!! npz 里没有 x_hat")
        sys.exit(3)
    x = d['x_hat']
    ref = np.fromfile(ref_p, dtype=np.float32)
    n = int(np.prod(x.shape))
    if ref.size != n:
        print("!! 尺寸不符: x_hat %s(%d) vs 参考 %d" % (x.shape, n, ref.size))
        sys.exit(4)
    ref = ref.reshape(x.shape[2], x.shape[3], x.shape[1])           # HWC
    ref = np.ascontiguousarray(ref.transpose(2, 0, 1))[None, ...]   # NCHW

    x = np.asarray(x, dtype=np.float32)
    diff = x - ref
    mse = float((diff ** 2).mean())
    psnr = 10.0 * np.log10(4.0 / max(mse, 1e-12))

    print("  %-10s PSNR = **%.2f dB**   (mse=%.6e, 最大绝对差 %.4f)"
          % (tag, psnr, mse, float(np.abs(diff).max())))
    print("             x_hat  范围 [%.3f, %.3f]  均值 %.4f"
          % (x.min(), x.max(), x.mean()))
    print("             参考   范围 [%.3f, %.3f]  均值 %.4f"
          % (ref.min(), ref.max(), ref.mean()))
    if 'y_hat' in d:
        y = d['y_hat']
        print("             y_hat  形状 %s 范围 [%.3f, %.3f]"
              % (y.shape, y.min(), y.max()))
    # 写一行给汇总用
    print("PSNR_LINE %s %.4f" % (tag, psnr))


if __name__ == '__main__':
    main()
