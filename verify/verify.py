# -*- coding: utf-8 -*-
"""校验**你的解码器**从 GLC2 int8 容器解出来的图，是否与 A 侧参考解码一致。

用法::

    python verify.py 你的解码.png            # 自动挑最接近的样本
    python verify.py 你的解码.png 2          # 指定样本 2

判据
----
主判据：与 `full_img{k}_rec.png` 的 PSNR。

    ≥ 40 dB   逐像素基本一致（只差 fp32 S4 的末位）      PASS
    32~40 dB  有可见但可接受的差异，通常是 S4 实现不同    PASS（会提示）
    < 32 dB   解错了                                        FAIL

参考尺度（实测）：解错一个相位就有 ~13~15 dB；完全解不开是 NaN。
所以 32 dB 这条线离"对的"和"错的"都很远，判据不敏感于阈值取多少。

同时打印每通道均值与 R-G（偏色指标），只用于定位，不参与判定。
"""
import os
import sys

import numpy as np
from PIL import Image

# Windows 控制台常是 GBK，个别符号会让 print 直接崩，这里兜住
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))

SAMPLES = [0, 1, 2, 3]
PSNR_PASS = 40.0
PSNR_WARN = 32.0


def psnr(a, b):
    mse = float(((a.astype(np.float64) - b.astype(np.float64)) ** 2).mean())
    return 99.0 if mse <= 0 else 10.0 * np.log10(255.0 ** 2 / mse)


def load(path):
    return np.asarray(Image.open(path).convert("RGB"))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    got = load(sys.argv[1])

    if len(sys.argv) > 2:
        try:
            k = int(sys.argv[2])
        except ValueError:
            print(__doc__)
            return 2
        if k not in SAMPLES:
            print("样本号只能是 0/1/2/3")
            return 2
        picks = [k]
        print("指定样本 %d" % k)
    else:
        picks = SAMPLES
        print("未指定样本，四个都试，取最接近的一个")

    best = None
    for k in picks:
        ref = load(os.path.join(HERE, "rec", "full_img%d.png" % k))
        if got.size != ref.size:
            print("!! 你的图是 %dx%d，参考是 %dx%d —— 尺寸不对，先查反归一化/裁剪"
                  % (got.shape[1], got.shape[0], ref.shape[1], ref.shape[0]))
            return 1
        p = psnr(got, ref)
        print("  样本 %d   PSNR vs rec.png = %6.2f dB" % (k, p))
        if best is None or p > best[1]:
            best = (k, p)

    k, p = best
    ref = load(os.path.join(HERE, "rec", "full_img%d.png" % k))
    dm = [abs(float(got[:, :, i].mean()) - float(ref[:, :, i].mean())) for i in range(3)]
    rg_got = float(got[:, :, 0].mean() - got[:, :, 1].mean())
    rg_ref = float(ref[:, :, 0].mean() - ref[:, :, 1].mean())

    print()
    print("最接近：样本 %d" % k)
    print("  通道均值差  R %.1f  G %.1f  B %.1f" % (dm[0], dm[1], dm[2]))
    print("  偏色 R-G    你的 %+.1f   参考 %+.1f   （差值 %+.1f）"
          % (rg_got, rg_ref, rg_got - rg_ref))
    print()

    if p >= PSNR_PASS:
        print("==> PASS：与参考解码一致（PSNR %.2f dB）" % p)
        return 0
    if p >= PSNR_WARN:
        print("==> PASS（有差异）：PSNR %.2f dB，低于 %.0f dB，通常是 S4 生成器实现不同"
              % (p, PSNR_PASS))
        print("    若你用的是同一份 fp32 S4，这里应该是 40 dB 以上甚至 ∞。")
        return 0

    print("==> FAIL：PSNR %.2f dB" % p)
    print("""
按这个顺序查（GLC2 容器不存 scales/means，解码端必须自己重推）：

  1. 先确认容器 md5 —— 见 check.py。不是同一份容器，后面都白搭。
  2. 你用的 _ZG 子图和发布的是不是同一份？见 MANIFEST.md 里的模型 md5。
     s2/s3p1-3 四个子图的 json+raw 八个数必须逐个对上。
  3. 解码用的是不是**同一套 int8 子图**？用 fp32 PyTorch 参考实现去解
     int8 容器会整段失步（实测 = NaN 或 ~13 dB）。
  4. 胶水层的 1x1 卷积（768→256）必须用 **float64 累加** 再转 float32，
     否则末位差会经 S3 的 int8 量化边界放大成符号翻转。见 AB板/
     02_A侧代码/07_解码端/工具/pc_decode_selfcontained.py 的 conv1x1()。
  5. HostRunner 的入参是 **NCHW**（内部自己转 NHWC）。转置两次会得到
     "36%~42% 元素恰好相同" 的假象。
""")
    return 1


if __name__ == "__main__":
    sys.exit(main())
