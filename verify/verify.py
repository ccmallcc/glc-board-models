# -*- coding: utf-8 -*-
"""校验 B 端解码结果是否与 A 侧参考实现一致。

用法::

    python verify.py 你们的解码输出.png

判据：PSNR ≥ 24 dB、每通道均值差 ≤ 6、偏色指标 |R−G| ≤ 20。
不通过时会打印每通道的 y=a·x+b 拟合，并给出最可能的原因。
"""
import sys

import numpy as np
from PIL import Image

REF = 'rec.png'
PSNR_MIN = 24.0
MEAN_TOL = 6.0
RG_TOL = 20.0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    got = Image.open(sys.argv[1]).convert('RGB')
    ref = Image.open(REF).convert('RGB')
    if got.size != ref.size:
        got = got.resize(ref.size, Image.LANCZOS)
        print('[!] 尺寸不同，已缩放到 %s 再比' % (ref.size,))
    g = np.asarray(got, dtype=np.float64)
    r = np.asarray(ref, dtype=np.float64)

    mse = float(((g - r) ** 2).mean())
    psnr = 99.0 if mse <= 0 else 10 * np.log10(255.0 ** 2 / mse)
    dm = [abs(g[:, :, i].mean() - r[:, :, i].mean()) for i in range(3)]
    rg_g = g[:, :, 0].mean() - g[:, :, 1].mean()
    rg_r = r[:, :, 0].mean() - r[:, :, 1].mean()

    print('PSNR        %.2f dB   (判据 ≥ %.0f)' % (psnr, PSNR_MIN))
    print('通道均值差  R %.1f  G %.1f  B %.1f   (判据 ≤ %.0f)' % (dm[0], dm[1], dm[2], MEAN_TOL))
    print('偏色 R−G    你的 %+.1f   参考 %+.1f   (判据 |差| ≤ %.0f)'
          % (rg_g, rg_r, RG_TOL))
    print('你的均值    R%.1f G%.1f B%.1f' % tuple(g[:, :, i].mean() for i in range(3)))
    print('参考均值    R%.1f G%.1f B%.1f' % tuple(r[:, :, i].mean() for i in range(3)))

    ok = (psnr >= PSNR_MIN and max(dm) <= MEAN_TOL and abs(rg_g - rg_r) <= RG_TOL)
    if ok:
        print('\n==> PASS：与参考实现一致（差异在量化误差范围内）')
        return 0

    print('\n==> FAIL：与参考实现不一致')
    # 每通道线性拟合：你的 = a*参考 + b
    print('\n每通道拟合（你的输出 = a × 参考 + b）:')
    for i, n in enumerate('RGB'):
        x = r[:, :, i].ravel()
        y = g[:, :, i].ravel()
        A = np.vstack([x, np.ones_like(x)]).T
        a, b = np.linalg.lstsq(A, y, rcond=None)[0]
        sat = (g[:, :, i] >= 250).mean() * 100
        print('  %s: a=%5.2f  b=%+7.1f   饱和(>=250) %5.1f%%' % (n, a, b, sat))
    print("""
对照这张表定位：
  · 三通道 a/b 差很多、某通道大量饱和  → 反归一化常数（每通道 mean/std）用错
  · R 被整体抬高（如 b≈+190）、G 被压缩 → YCoCg / YUV→RGB 的矩阵或偏移写错
  · 某通道大面积饱和                   → int8 反量化的 scale / zero-point 用错
  · 仅整体亮度略偏、结构一致            → 正常量化误差，可放宽判据
""")
    return 1


if __name__ == '__main__':
    sys.exit(main())
