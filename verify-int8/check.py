# -*- coding: utf-8 -*-
"""GLC2 验收向量自检（Tier 1：零依赖，只需 numpy + Pillow）。

校验两件事：
  1. 12 个文件的 md5 与发布值一致 —— 证明你拿到的是同一份东西；
  2. 源图 vs 参考解码图的 PSNR —— 证明公开的码率/质量数字没编。

用法::

    python check.py            # 跑全部
    python check.py 2          # 只跑样本 2

注意：本脚本**不解码容器**。容器的可解码性见 README.md 的 Tier 2。
"""
import hashlib
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

# ------------------------------------------------------------------ 发布值
# (相对路径, 字节数, md5)  —— 任何一项不符即为"不是同一份文件"
FILES = {
    "glc/full_img0.glc": (324, "23148d29e133e4b9dfae5ffe99274dbe"),
    "glc/full_img1.glc": (316, "d4b9476b29c71d42ae66041c88ac5ce9"),
    "glc/full_img2.glc": (316, "a2658789b6295571893f7cf4c1e1c293"),
    "glc/full_img3.glc": (312, "eabd2cc5929678de836a11944d7257b8"),
    "src/full_img0.png": (128045, "ebb42f0f587b83592bbaf04771f5150d"),
    "src/full_img1.png": (111204, "3ee9bc714e8b7c47a07ef6a25bd4de16"),
    "src/full_img2.png": (104265, "271bad4ae58a4fd013bedb914eb2f741"),
    "src/full_img3.png": (100865, "26288ab732f4ad7935dc7d343b56d30d"),
    "rec/full_img0.png": (143552, "639185ec363a3a3172c3a81b0e497bdd"),
    "rec/full_img1.png": (113995, "bc8b4699252a9d1a1070d821691963ea"),
    "rec/full_img2.png": (126604, "65e97e479f55018067da8d5596a34a28"),
    "rec/full_img3.png": (116339, "ae8d8d3d739283dd4cace61000ff72ae"),
}

# 源图 vs 参考解码，uint8 域实算（float 域是 18.1913/22.9885/19.7931/25.4205，
# 转 uint8 后末位略有差别，这里以 uint8 域为准）
EXPECT_PSNR = {0: 18.1906, 1: 22.9879, 2: 19.7927, 3: 25.4183}
PSNR_TOL = 0.02

EXPECT_BPP = {0: 0.03955, 1: 0.03857, 2: 0.03857, 3: 0.03809}


def md5_of(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def psnr_u8(a, b):
    mse = float(((a.astype(np.float64) - b.astype(np.float64)) ** 2).mean())
    return 99.0 if mse <= 0 else 10.0 * np.log10(255.0 ** 2 / mse)


def main():
    want = None
    if len(sys.argv) > 1:
        try:
            want = int(sys.argv[1])
        except ValueError:
            print(__doc__)
            return 2
    if want is not None and want not in (0, 1, 2, 3):
        print("样本号只能是 0/1/2/3")
        return 2

    bad = 0
    print("=" * 72)
    print("[1/2] 文件指纹")
    print("=" * 72)
    for name in sorted(FILES):
        if want is not None and ("/full_img%d." % want) not in name:
            continue
        path = os.path.join(HERE, name)
        if not os.path.exists(path):
            print("  %-22s 缺失" % name)
            bad += 1
            continue
        size = os.path.getsize(path)
        md5 = md5_of(path)
        want_size, want_md5 = FILES[name]
        ok = (size == want_size and md5 == want_md5)
        bad += 0 if ok else 1
        print("  %-22s %8d B  %s  %s"
              % (name, size, md5, "OK" if ok else "!! 与发布值不符"))

    print()
    print("=" * 72)
    print("[2/2] 质量指标（源图 vs 参考解码，uint8 域）")
    print("=" * 72)
    ps = []
    for k in sorted(EXPECT_PSNR):
        if want is not None and k != want:
            continue
        src = np.asarray(Image.open(os.path.join(HERE, "src", "full_img%d.png" % k)).convert("RGB"))
        rec = np.asarray(Image.open(os.path.join(HERE, "rec", "full_img%d.png" % k)).convert("RGB"))
        p = psnr_u8(src, rec)
        ps.append(p)
        ok = abs(p - EXPECT_PSNR[k]) <= PSNR_TOL
        bad += 0 if ok else 1
        print("  样本 %d  %4d B  bpp=%.5f  PSNR=%6.2f dB  (期望 %.2f)  %s"
              % (k, FILES["glc/full_img%d.glc" % k][0], EXPECT_BPP[k], p,
                 EXPECT_PSNR[k], "OK" if ok else "!! 不符"))
    if ps:
        print("  平均    %6.2f dB" % (sum(ps) / len(ps)))

    print()
    if bad:
        print("==> FAIL：%d 项不符" % bad)
        return 1
    print("==> PASS：文件指纹与质量指标均与发布值一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
