# -*- coding: utf-8 -*-
r"""把板端 dump 出来的 x_hat（NHWC float32 ftmp）与 PC 上的 fp32 参考（torch NCHW .npy）比较。

判据：int8 量化后的板端输出与 fp32 参考之间的 PSNR / 相对误差。
用途：给"512 拆段后 int8 精度是否正常"一个**基线** —— 先量 256（已在用的那一版）的误差，
再看 512 拆段后是不是同一量级。只看 512 自己有没有坏，不如跟 256 比。

用法：
  python cmp_xhat.py --board a.ftmp --ref r.npy --hwc 512,512,3
"""
import argparse

import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--board', required=True)
    ap.add_argument('--ref', required=True)
    ap.add_argument('--hwc', default='512,512,3')
    a = ap.parse_args()
    H, W, C = [int(x) for x in a.hwc.split(',')]

    b = np.fromfile(a.board, dtype=np.float32)
    if b.size != H * W * C:
        print('!! 板端文件 %d 元素，期望 %d' % (b.size, H * W * C))
        return 2
    b = b.reshape(1, H, W, C).transpose(0, 3, 1, 2)          # -> NCHW
    r = np.load(a.ref).astype(np.float32)
    if r.shape != b.shape:
        print('!! 形状不符：板端 %s 参考 %s' % (b.shape, r.shape))
        return 2

    d = b - r
    mse = float(np.mean(d * d))
    ref_p = float(np.max(r) - np.min(r)) or 1.0
    psnr = 10 * np.log10((ref_p ** 2) / mse) if mse > 0 else float('inf')
    rel = float(np.linalg.norm(d) / (np.linalg.norm(r) or 1.0))
    print('板端 %s' % a.board)
    print('  元素 %d   板端 min %.4f max %.4f mean %.4f | 参考 min %.4f max %.4f mean %.4f'
          % (b.size, b.min(), b.max(), b.mean(), r.min(), r.max(), r.mean()))
    print('  max|diff| %.5f   RMSE %.5f   相对L2 %.4f%%   动态范围PSNR %.2f dB'
          % (float(np.max(np.abs(d))), mse ** 0.5, rel * 100.0, psnr))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
