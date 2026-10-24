# -*- coding: utf-8 -*-
r"""PC 端全链路基准：**编码（含算术编码）+ 解码（含算术解码）**，CPU vs 独显。

用于回答"板子值不值"：同一条 GLC 流水线，在 PC 的 dGPU 上跑要多久。

用法（WSL Ubuntu-22.04，有 compressai + CUDA）::

    python3 bench_pc_chain.py --device cuda --n 4
    python3 bench_pc_chain.py --device cpu  --n 4
"""
import argparse
import json
import math
import os
import sys
import time
import types

import numpy as np
import torch
from PIL import Image


def psnr(a, b):
    mse = float(((a - b) ** 2).mean())
    return 10 * math.log10(4.0 / max(mse, 1e-12))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="/mnt/e/fudanwei/工作区/GLC-main/GLC-main")
    ap.add_argument("--model", default="/mnt/e/fudanwei/工作区/GLC-main/GLC-main/pretrained/GLC_image.pth.tar")
    ap.add_argument("--png_dir", default="/mnt/e/fudanwei/工作区/testset/kodak_real")
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--q", type=int, default=0)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--warmup", type=int, default=2)
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    repo = os.path.abspath(a.repo)
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "src", "utils"))
    stub = types.ModuleType("src.utils.metric_image")
    stub.evaluate_quality = lambda *x, **k: None
    sys.modules["src.utils.metric_image"] = stub

    import torch.nn.functional as F
    import test_image_complement2 as T
    from src.models.image_model import GLC_Image
    from src.utils.test_utils import get_state_dict, init_func

    init_func()
    dev = torch.device(a.device if (a.device != "cuda" or torch.cuda.is_available())
                       else "cpu")
    model = GLC_Image(inplace=True).to(dev)
    model.load_state_dict(get_state_dict(a.model), strict=True)
    model.eval()
    em = T.build_entropy_model(dev)
    T.validate_entropy_codec(em, dev)

    pngs = sorted(f for f in os.listdir(a.png_dir) if f.lower().endswith(".png"))
    S = a.size

    def load(i):
        im = Image.open(os.path.join(a.png_dir, pngs[i % len(pngs)])).convert("RGB")
        w, h = im.size
        x0, y0 = (i * 37) % max(1, w - S), (i * 53) % max(1, h - S)
        px = np.asarray(im.crop((x0, y0, x0 + S, y0 + S)), dtype=np.float32) / 127.5 - 1.0
        x = torch.from_numpy(px.transpose(2, 0, 1)).unsqueeze(0).to(dev)
        pad = GLC_Image.get_padding_size(S, S, 64)
        return F.pad(x, pad, mode="replicate")

    def sync():
        if dev.type == "cuda":
            torch.cuda.synchronize(dev)

    def one(x):
        t0 = time.perf_counter()
        with torch.no_grad():
            blob, _ = T.compress_glc(model, em, x, a.q, (S, S))
        sync()
        t_enc = time.perf_counter() - t0

        t0 = time.perf_counter()
        with torch.no_grad():
            rec, _y = T.decompress_glc(model, em, blob)
        sync()
        t_dec = time.perf_counter() - t0
        return blob, rec, t_enc, t_dec

    # 热身（CUDA 首次调用有初始化）
    for i in range(a.warmup):
        one(load(i))

    rows = []
    for i in range(a.n):
        x = load(i)
        blob, rec, t_enc, t_dec = one(x)
        xc = x[:, :, :S, :S].clamp(-1, 1)
        rows.append(dict(sample=i, png=pngs[i % len(pngs)], bytes=len(blob),
                         bpp=len(blob) * 8 / (S * S),
                         enc_ms=t_enc * 1000, dec_ms=t_dec * 1000,
                         total_ms=(t_enc + t_dec) * 1000,
                         psnr=psnr(rec, xc)))
        r = rows[-1]
        print("  %-12s %4dB bpp=%.5f  编码=%7.1f 解码=%7.1f 合计=%7.1f ms  PSNR=%.2f"
              % (r["png"], r["bytes"], r["bpp"], r["enc_ms"], r["dec_ms"],
                 r["total_ms"], r["psnr"]))

    n = len(rows)
    agg = {k: sum(r[k] for r in rows) / n for k in
           ("bytes", "bpp", "enc_ms", "dec_ms", "total_ms", "psnr")}
    name = torch.cuda.get_device_name(0) if dev.type == "cuda" else "CPU"
    print("\n===== %s (%s) 平均 over %d =====" % (dev.type.upper(), name, n))
    print("  容器 %.1f B  bpp=%.5f  PSNR=%.2f" % (agg["bytes"], agg["bpp"], agg["psnr"]))
    print("  编码 %.1f ms + 解码 %.1f ms = %.1f ms  (%.2f fps)"
          % (agg["enc_ms"], agg["dec_ms"], agg["total_ms"], 1000.0 / agg["total_ms"]))
    if a.out:
        json.dump(dict(rows=rows, agg=agg, device=str(dev), name=name),
                  open(a.out, "w"), indent=2, ensure_ascii=False)
        print("  报告:", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
