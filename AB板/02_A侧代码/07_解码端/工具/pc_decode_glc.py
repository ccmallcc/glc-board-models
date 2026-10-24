# -*- coding: utf-8 -*-
r"""PC 侧解码：吃**板端产的**真 .glc，量解码延时与重建质量。

解码路径 = compressai 算术解码（rANS 等价） -> model.dec -> S4 生成器（fp32）

用法::

    python pc_decode_glc.py --glc_dir <dir> --n 4 --q 0
"""
import argparse
import os
import sys
import time
import types

import numpy as np
import torch
from PIL import Image


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=r"E:\fudanwei\工作区\GLC-main\GLC-main")
    ap.add_argument("--model", default=r"E:\fudanwei\工作区\GLC-main\GLC-main\pretrained\GLC_image.pth.tar")
    ap.add_argument("--glc_dir", required=True)
    ap.add_argument("--png_dir", default=r"E:\fudanwei\工作区\testset\kodak_real")
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    repo = os.path.abspath(a.repo)
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "src", "utils"))
    stub = types.ModuleType("src.utils.metric_image")
    stub.evaluate_quality = lambda *x, **k: None
    sys.modules["src.utils.metric_image"] = stub

    import test_image_complement2 as T
    from src.models.image_model import GLC_Image
    from src.utils.test_utils import get_state_dict, init_func

    init_func()
    dev = torch.device(a.device if torch.cuda.is_available() else "cpu")
    model = GLC_Image(inplace=True).to(dev)
    model.load_state_dict(get_state_dict(a.model), strict=True)
    model.eval()
    em = T.build_entropy_model(dev)

    pngs = sorted(f for f in os.listdir(a.png_dir) if f.lower().endswith(".png"))
    S = a.size

    # 熵解码器的热身（第一次调用有懒初始化，不计入统计）
    files = sorted(f for f in os.listdir(a.glc_dir) if f.endswith(".glc"))
    warm = os.path.join(a.glc_dir, files[0])
    with torch.no_grad():
        T.decompress_glc(model, em, open(warm, "rb").read())

    rows = []
    for i, fn in enumerate(files[:a.n]):
        blob = open(os.path.join(a.glc_dir, fn), "rb").read()
        t0 = time.perf_counter()
        with torch.no_grad():
            recon, y_hat = T.decompress_glc(model, em, blob)
        t1 = time.perf_counter()

        im = Image.open(os.path.join(a.png_dir, pngs[i % len(pngs)])).convert("RGB")
        w, h = im.size
        x0, y0 = (i * 37) % max(1, w - S), (i * 53) % max(1, h - S)
        px = np.asarray(im.crop((x0, y0, x0 + S, y0 + S)), dtype=np.float32) / 127.5 - 1.0
        x = torch.from_numpy(px.transpose(2, 0, 1)).unsqueeze(0)
        rec = recon.clamp(-1, 1)
        mse = float(((rec - x.clamp(-1, 1)) ** 2).mean())
        psnr = 10 * np.log10(4.0 / max(mse, 1e-12))
        rows.append(dict(glc=fn, bytes=len(blob), bpp=len(blob) * 8 / (S * S),
                         decode_ms=(t1 - t0) * 1000, psnr=psnr))
        print("  %-12s %5d B  bpp=%.5f  解码=%.1f ms  PSNR=%.2f"
              % (fn, len(blob), rows[-1]["bpp"], rows[-1]["decode_ms"], psnr))

    n = len(rows)
    print("\n===== PC 解码平均 over %d =====" % n)
    print("  容器 %.1f B   bpp=%.5f   解码=%.1f ms   PSNR=%.2f"
          % (sum(r["bytes"] for r in rows) / n, sum(r["bpp"] for r in rows) / n,
             sum(r["decode_ms"] for r in rows) / n,
             sum(r["psnr"] for r in rows) / n))
    if a.out:
        import json
        json.dump(rows, open(a.out, "w"), indent=2, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
