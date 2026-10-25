# -*- coding: utf-8 -*-
"""校验**你的解码器**解出来的图，是否与 A 侧参考解码一致。

    python verify.py 你的解码.png

判据：与 `rec.png` 的 PSNR。

    ≥ 40 dB   逐像素基本一致                                  PASS
    32~40 dB  有可见差异，通常是 S4 生成器实现不同             PASS（会提示）
    < 32 dB   解错了（或先验没对上）

参考尺度（实测 2026-10-25）：先验一旦失步，PSNR 落在 **12~15 dB**；
完全解不开是 NaN。32 dB 这条线离两边都很远。

本脚本**零依赖**（只要 numpy + Pillow），不需要模型、不需要跑解码。
"""
import os
import sys

import numpy as np
from PIL import Image

# Windows 控制台常是 GBK，个别符号会让 print 崩，这里兜住
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))

REF = os.path.join(HERE, "rec.png")
SRC = os.path.join(HERE, "IMG_0036.jpg")
PSNR_PASS = 40.0
PSNR_WARN = 32.0


def psnr(a, b):
    mse = float(((a.astype(np.float64) - b.astype(np.float64)) ** 2).mean())
    return 99.0 if mse <= 0 else 10.0 * np.log10(255.0 ** 2 / mse)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    got = np.asarray(Image.open(sys.argv[1]).convert("RGB"))
    ref = np.asarray(Image.open(REF).convert("RGB"))
    if got.shape != ref.shape:
        print("!! 你的图是 %dx%d，参考是 %dx%d —— 尺寸不对"
              % (got.shape[1], got.shape[0], ref.shape[1], ref.shape[0]))
        return 1

    p = psnr(got, ref)
    dm = [abs(float(got[:, :, i].mean()) - float(ref[:, :, i].mean())) for i in range(3)]
    rg_got = float(got[:, :, 0].mean() - got[:, :, 1].mean())
    rg_ref = float(ref[:, :, 0].mean() - ref[:, :, 1].mean())

    print("PSNR vs rec.png   %6.2f dB" % p)
    print("  通道均值差      R %.1f  G %.1f  B %.1f" % (dm[0], dm[1], dm[2]))
    print("  偏色 R-G        你的 %+.1f   参考 %+.1f   （差 %+.1f）"
          % (rg_got, rg_ref, rg_got - rg_ref))
    print("  你的均值        R%.1f G%.1f B%.1f"
          % tuple(got[:, :, i].mean() for i in range(3)))
    print("  参考均值        R%.1f G%.1f B%.1f"
          % tuple(ref[:, :, i].mean() for i in range(3)))
    print()

    if p >= PSNR_PASS:
        print("==> PASS：与参考解码一致（%.2f dB）" % p)
        return 0
    if p >= PSNR_WARN:
        print("==> PASS（有差异）：%.2f dB，低于 %.0f dB。" % (p, PSNR_PASS))
        print("    先验对上了、但 S4 生成器的实现不同。若用的是同一份 fp32 S4，这里应 ≥40 dB。")
        return 0

    print("==> FAIL：%.2f dB" % p)
    print("""
GLC2 容器不存 scales/means，解码端必须自己重推，且必须与编码端**逐位一致**。
按这个顺序查：

  1. 容器 md5 是不是 5b2a4571e1f605d36a3193c1b354eaed（见 README）。
  2. **是不是在 CPU 上解的？** 这个容器只能在 CPU 上解。CUDA 的 cuDNN 算法选择
     随进程变，同一份容器在 CUDA 上解出来是 NaN —— 连它自己产的容器都解不开。
  3. 权重是不是 GLC_image.pth.tar，md5 41453cd3f45dcd505ef637d754df76cd。
  4. 题头 padding 必须 `replicate`、q_index 必须取自容器头（本向量是 0）。
  5. 先验那一步不能改 accumulate 顺序（比如把 Conv2d 换成手写 im2col）。
""")
    return 1


if __name__ == "__main__":
    sys.exit(main())
