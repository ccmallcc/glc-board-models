# -*- coding: utf-8 -*-
"""A/023 九块重叠（MODE=3）测试向量 · 自检脚本

三件事，任何一件失败都说明实现有问题：

① 文件完整性：所有文件 md5 与 md5sums.txt 一致。
② 几何+权重：把 **9 个源图裁剪块**（tile01..09.png）按 A/021 §5 的权重融合，
   必须**逐像素还原** source_512.png（最大误差 ≤ 1 LSB）。这条与编码器无关。
③ 编码结果（可选）：如果你已用 B 端解码器把 tile01..09.glc 解成 dec_tile01..09.png，
   放进本目录后重跑，脚本会融合并给出 PSNR（无固定缝位，故不算接缝比）。

用法：
    python verify.py                 # 只做 ①②
    python verify.py --decoded       # 额外做 ③（需要 dec_tile01..09.png）
"""
import argparse
import hashlib
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
COORDS = [(0, 0), (0, 128), (0, 256),
          (128, 0), (128, 128), (128, 256),
          (256, 0), (256, 128), (256, 256)]


def flat_top(n=256, ramp=64):
    t = np.arange(n, dtype=np.float32)
    w = np.ones(n, np.float32)
    m = t < ramp
    w[m] = 0.5 - 0.5 * np.cos(np.pi * (t[m] + 0.5) / ramp)
    m2 = t >= n - ramp
    w[m2] = 0.5 - 0.5 * np.cos(np.pi * (n - t[m2] - 0.5) / ramp)
    return w


def blend(tiles):
    WY, WX = flat_top()[:, None], flat_top()[None, :]
    out = np.zeros((512, 512, 3), np.float32)
    wt = np.zeros((512, 512, 1), np.float32)
    for i, (y, x) in enumerate(COORDS):
        w = (WY * WX)[..., None]
        out[y:y + 256, x:x + 256] += tiles[i] * w
        wt[y:y + 256, x:x + 256] += w
    return out / np.maximum(wt, 1e-12)          # ★ 下限 1e-12，不要用 1e-6


def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def check_md5():
    ok = bad = 0
    for line in open(os.path.join(HERE, "md5sums.txt"), encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        h, name = line.split(None, 1)
        name = name.strip().lstrip("*")
        p = os.path.join(HERE, name)
        if not os.path.exists(p):
            print("  ✗ 缺文件 %s" % name)
            bad += 1
        elif md5(p) != h:
            print("  ✗ md5 不符 %s" % name)
            bad += 1
        else:
            ok += 1
    print("① md5：%d 通过 / %d 失败" % (ok, bad))
    return bad == 0


def check_geometry():
    src = np.asarray(Image.open(os.path.join(HERE, "source_512.png")).convert("RGB"), np.float32)
    tiles = [np.asarray(Image.open(os.path.join(HERE, "tile%02d.png" % (i + 1))).convert("RGB"), np.float32)
             for i in range(9)]
    out = blend(tiles)
    err = np.abs(out - src)
    print("② 几何+权重：最大误差 %.4f LSB，平均 %.6f LSB（要求 ≤ 1）" % (err.max(), err.mean()))
    return err.max() <= 1.0


def check_decoded():
    src = np.asarray(Image.open(os.path.join(HERE, "source_512.png")).convert("RGB"), np.float32)
    tiles = [np.asarray(Image.open(os.path.join(HERE, "dec_tile%02d.png" % (i + 1))).convert("RGB"), np.float32)
             for i in range(9)]
    out = blend(tiles)
    mse = np.mean((out - src) ** 2)
    psnr = 10 * np.log10(255.0 ** 2 / max(mse, 1e-9))
    Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save(os.path.join(HERE, "decoded_blend.png"))
    print("③ 解码块融合：PSNR %.2f dB（相对源图）；已写 decoded_blend.png" % psnr)
    return psnr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decoded", action="store_true")
    a = ap.parse_args()
    ok1 = check_md5()
    ok2 = check_geometry()
    if a.decoded:
        check_decoded()
    print("\n结论：", "全部通过" if (ok1 and ok2) else "**有失败项**")
    return 0 if (ok1 and ok2) else 1


if __name__ == "__main__":
    raise SystemExit(main())
