#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""大图模式的分块器：把一张「大图」切成 4 块 256×256（小图模式则中心裁 1 块）。

为什么在**发送前**切，而不是让相机直接出 4 块：
  · 相机一次曝光拿到整幅画面，切成 4 块后每块都还能用**现成的 256 链路**编码
    （模型、容器、PL rANS 一行都不用改）；
  · 4 块共用同一次曝光，**块间没有时间差**，拼回去不会有运动错位。

块的顺序是**固定的、顺时针**（B 端要按这个顺序拼）：
    0: 左上 (0,0)      1: 右上 (0,256)
    2: 右下 (256,256)  3: 左下 (256,0)
★ 2026-10-23 改：原来是行优先 TL,TR,BL,BR；用户明确要**顺时针 TL,TR,BR,BL**，
  所以第 3、4 块互换。B 端尚未实现，改这一刀没有兼容包袱。

用法:
  python3 tile_split.py --in big.jpg --outdir /root/send_work/big --big    # 出 000..003.jpg
  python3 tile_split.py --in big.jpg --outdir /root/send_work/sml --small  # 出 000.jpg（整幅缩到 256）
"""
import argparse
import os
import sys

from PIL import Image

SIZE = 256
BIG = SIZE * 2          # 512：大图边长 = 2×小图


def fit_big(im):
    """把输入规整成 512×512。

    优先**中心裁**（不重采样、不丢分辨率）；画面比 512 小时才放大。
    相机若已按 512×512 出图，这一步是恒等变换。
    """
    w, h = im.size
    if w >= BIG and h >= BIG:
        x0 = (w - BIG) // 2
        y0 = (h - BIG) // 2
        return im.crop((x0, y0, x0 + BIG, y0 + BIG))
    s = min(w, h)
    x0 = (w - s) // 2
    y0 = (h - s) // 2
    return im.crop((x0, y0, x0 + s, y0 + s)).resize((BIG, BIG), Image.LANCZOS)


def full_small(im):
    """小图 = **整幅缩放到 256×256**（用户 2026-10-23 定：不要中心裁）。

    为什么改：中心裁只剩 512 里中间那一块（视场 1/4），大图却是**整幅** ——
    同一个场景两种模式看到的范围不一样，演示时很难解释。改成整幅缩放后：
      **小图 = 整幅低分辨率版（256）**，**大图 = 整幅高分辨率版（512，4 块拼）**。
    代价只是多一次 LANCZOS 缩放（512→256，板上实测 1~2 ms 量级）。

    非方图会被压成正方形 —— 与编码器 `prepare(mode='fit')` 的行为一致（它本来也是直接 resize）。
    """
    return im.resize((SIZE, SIZE), Image.LANCZOS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='src', required=True)
    ap.add_argument('--outdir', required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--big', action='store_true')
    g.add_argument('--small', action='store_true')
    ap.add_argument('--quality', type=int, default=92, help='JPEG 质量（默认与 UI 存盘一致）')
    a = ap.parse_args()

    if not os.path.isfile(a.src):
        print('TILE_FAIL 输入不存在 %s' % a.src)
        return 2
    os.makedirs(a.outdir, exist_ok=True)
    im = Image.open(a.src).convert('RGB')

    outs = []
    if a.small:
        dst = os.path.join(a.outdir, '000.jpg')
        full_small(im).save(dst, quality=a.quality)
        outs.append(dst)
    else:
        big = fit_big(im)
        # 顺时针：左上 → 右上 → 右下 → 左下
        boxes = [(0, 0), (0, SIZE), (SIZE, SIZE), (SIZE, 0)]
        for i, (y0, x0) in enumerate(boxes):
            dst = os.path.join(a.outdir, '%03d.jpg' % i)
            big.crop((x0, y0, x0 + SIZE, y0 + SIZE)).save(dst, quality=a.quality)
            outs.append(dst)

    for p in outs:
        print('TILE %s %d B' % (p, os.path.getsize(p)))
    print('TILE_DONE n=%d mode=%s' % (len(outs), 'big' if a.big else 'small'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
