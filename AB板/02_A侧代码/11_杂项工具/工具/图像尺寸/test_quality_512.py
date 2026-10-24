# -*- coding: utf-8 -*-
r"""★ 决定性实验：512x512（latent 32x32）下，画质会不会崩？

原理：权重是在 latent 16x16（图 256x256）上训练的。
      换成 latent 32x32（图 512x512）在数学上自洽（误差 0），
      但**可能落在训练分布之外** => 重建画质可能崩。

做法：拿同一张真实图，分别缩到 256 和 512，各跑一次模型的完整前向
      （model.test(x, q) = 编码 -> 量化 -> 解码），算 PSNR 和 bpp，直接对比。

这一步**不需要 icraft、不需要板子**，纯 PC。若 512 的画质和 256 差不多，
这条路就通了；若明显掉，说明必须重新训练。
"""
import os
import sys

import numpy as np
import torch
from PIL import Image

REPO = r'E:\fudanwei\工作区\GLC-main\GLC-main'
MODEL = os.path.join(REPO, 'pretrained', 'GLC_image.pth.tar')
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, 'src', 'utils'))

IMGS = [r'E:\fudanwei\photo\微信图片_20261008225109_479_23.jpg',
        r'E:\fudanwei\photo\微信图片_20261008225113_483_23.jpg',
        r'E:\fudanwei\photo\微信图片_20261008225115_485_23.jpg']


def load(path, size):
    im = Image.open(path).convert('RGB')
    w, h = im.size
    s = size / min(w, h)
    im = im.resize((max(size, int(round(w * s))), max(size, int(round(h * s)))), Image.LANCZOS)
    w2, h2 = im.size
    l, t = (w2 - size) // 2, (h2 - size) // 2
    im = im.crop((l, t, l + size, t + size))
    a = np.asarray(im, dtype=np.float32) / 127.5 - 1.0     # [-1,1]
    return torch.from_numpy(a).permute(2, 0, 1)[None, ...]  # (1,3,S,S)


def psnr(a, b):
    mse = float(np.mean((a - b) ** 2))
    if mse <= 0:
        return 99.0
    return 10 * np.log10(4.0 / mse)      # 值域 [-1,1] => 峰峰值 2，2^2=4


print('=' * 84)
print('  512x512 (latent 32x32) vs 256x256 (latent 16x16)  —— 画质对比')
print('=' * 84)

from src.models.image_model import GLC_Image
from src.utils.test_utils import get_state_dict

model = GLC_Image(inplace=True)
model.load_state_dict(get_state_dict(MODEL), strict=True)
model.eval()
print('  模型已载入\n')

hdr = '  %-34s %6s %8s %8s %8s %8s' % ('图片', '尺寸', 'bpp', 'MSE', 'PSNR', '对比')
print(hdr)
print('  ' + '-' * (len(hdr) - 2))

for path in IMGS:
    if not os.path.exists(path):
        print('  缺 %s' % os.path.basename(path))
        continue
    name = os.path.basename(path)[:26]
    res = {}
    for size in (256, 512):
        x = load(path, size)
        with torch.no_grad():
            out = model.test(x, 0)
        x_hat = out['x_hat']
        # bpp 视不同版本可能在 out 里，取不到就留空
        bpp = None
        for k in ('bpp', 'bitrate', 'rate'):
            if k in out:
                v = out[k]
                bpp = float(v) if np.isscalar(v) or torch.is_tensor(v) else None
                if torch.is_tensor(v):
                    bpp = float(v.mean())
                break
        a = x[0].permute(1, 2, 0).numpy()
        b = x_hat[0].permute(1, 2, 0).numpy()
        mse = float(np.mean((a - b) ** 2))
        p = psnr(a, b)
        res[size] = (bpp, mse, p)
        print('  %-34s %6d %8s %8.5f %8.2f' %
              (name if size == 256 else '', size,
               ('%.4f' % bpp) if bpp is not None else '?', mse, p))
    if 256 in res and 512 in res:
        d = res[512][2] - res[256][2]
        print('  %-34s %6s %8s %8s %+8.2f  ← %s' %
              ('', '', '', '', d,
               '✅ 512 不差' if d > -0.5 else ('⚠️ 512 略差' if d > -3 else '❌ 512 明显崩')))
    print()

print('=' * 84)
print('  判读标准：')
print('    · ΔPSNR > -0.5 dB  => 权重泛化良好，512 这条路通')
print('    · ΔPSNR < -3  dB   => 严重分布外，必须重新训练')
print('=' * 84)
print('QUALITY_512_DONE')
