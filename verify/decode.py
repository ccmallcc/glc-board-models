#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""GLC2 参考解码器（fp32，**必须 CPU**）。

它只吃一个 308 B 的 `.glc`，不碰任何旁路数据：解码端自己从 z 的 16 个索引
重推出每个相位的 scales/means，再用 rANS 反解 4 段符号，最后过 S4 生成器。

    python decode.py IMG_0036.glc --out rec.png

前置
----
1. GLC 官方参考实现（`test_image_complement2.py` + `src/`）
2. 权重 `GLC_image.pth.tar`，md5 `41453cd3f45dcd505ef637d754df76cd`（667,371,692 B）

为什么要钉死 CPU
----------------
`GLC2` 容器不存 scales/means，解码端必须重算，**且必须与编码端逐位一致**，
否则 rANS 状态机整段失步。而：

    CPU  路径：跨进程、跨线程数都逐位一致（实测 2026-10-25）
    CUDA 路径：同一进程内自洽，**换个进程就不一样**（cuDNN 算法自动选择随进程变），
              连它自己产的容器都解不开

所以本向量在 CPU 上产出，也必须用 CPU 解。给 `--device cuda` 会直接报错退出。
"""
import argparse
import hashlib
import math
import os
import sys
import types

import numpy as np
import torch
from PIL import Image

S = 256


def psnr(a, b):
    mse = float(((a - b) ** 2).mean())
    return 10 * math.log10(4.0 / max(mse, 1e-12))


def load(T_repo, ckpt, device):
    sys.path.insert(0, T_repo)
    sys.path.insert(0, os.path.join(T_repo, "src", "utils"))
    stub = types.ModuleType("src.utils.metric_image")
    stub.evaluate_quality = lambda *x, **k: None
    sys.modules["src.utils.metric_image"] = stub

    import test_image_complement2 as T
    from src.models.image_model import GLC_Image
    from src.utils.test_utils import get_state_dict, init_func

    init_func()
    dev = torch.device(device)
    model = GLC_Image(inplace=True).to(dev)
    model.load_state_dict(get_state_dict(ckpt), strict=True)
    model.eval()
    return T, model, T.build_entropy_model(dev), dev


def to_u8(t):
    arr = t[0].clamp(-1, 1).cpu().numpy().transpose(1, 2, 0)
    return ((arr + 1.0) * 127.5).round().clip(0, 255).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("glc")
    ap.add_argument("--img", default="", help="原图，给了就顺带算 PSNR")
    ap.add_argument("--out", default="rec.png")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--repo", default=os.environ.get(
        "GLC_REPO", "/mnt/e/fudanwei/工作区/GLC-main/GLC-main"))
    ap.add_argument("--model", default=os.environ.get(
        "GLC_MODEL", ""), help="默认 <repo>/pretrained/GLC_image.pth.tar")
    a = ap.parse_args()

    if a.device != "cpu":
        sys.exit("本向量必须在 CPU 上解：%s 路径不可跨进程复现（见文件头）。" % a.device)

    ckpt = a.model or os.path.join(a.repo, "pretrained", "GLC_image.pth.tar")
    for p in (a.repo, ckpt):
        if not os.path.exists(p):
            sys.exit("缺文件：%s" % p)

    T, model, em, dev = load(a.repo, ckpt, a.device)
    blob = open(a.glc, "rb").read()
    print("容器 %d B  md5=%s" % (len(blob), hashlib.md5(blob).hexdigest()))

    with torch.no_grad():
        rec, _ = T.decompress_glc(model, em, blob)

    u8 = to_u8(rec)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    Image.fromarray(u8).save(a.out)
    print("解码图 %s  md5=%s" % (a.out, hashlib.md5(open(a.out, "rb").read()).hexdigest()))

    if a.img:
        im = Image.open(a.img).convert("RGB")
        if im.size != (S, S):
            im = im.resize((S, S), Image.LANCZOS)
        x = torch.from_numpy(
            (np.asarray(im, dtype=np.float32) / 127.5 - 1.0).transpose(2, 0, 1)
        ).unsqueeze(0).to(dev)
        print("PSNR vs 原图 = %.2f dB" % psnr(rec, x.clamp(-1, 1)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
