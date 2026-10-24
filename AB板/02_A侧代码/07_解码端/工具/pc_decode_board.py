# -*- coding: utf-8 -*-
r"""PC 侧解码**板端码流**（在 WSL 跑，因为 compressai 只在那儿有）。

背景（V16 §5）：GLC2 容器不存 scales/means，解码时必须由**解码侧**重算。
板端编码用的是 INT8 的 S2/S3，PC 的 `decompress_glc` 用 fp32 => 必然对不上。

本脚本的做法：解码侧的 scales/means **由编码端导出**（它们本来就是
"z + 已解码阶段"的确定函数，值逐位相同），于是可以验证：

    .glc 容器 + 正确的熵参数  ==>  正确的图像（PSNR 正常）

从而把"码流正确"与"PC fp32 模型不匹配"两件事彻底分开。
S2/S3 在 PC 上的实际耗时单独测（HostBackend，见报告）。

用法::

    python3 pc_decode_board.py --glc_dir <dir> --ops_dir <operands parent> --n 4
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
    ap.add_argument("--glc_dir", required=True)
    ap.add_argument("--ops_dir", required=True, help="包含 img0/ img1/ ... 的目录")
    ap.add_argument("--png_dir", default="/mnt/e/fudanwei/工作区/testset/kodak_real")
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
    dev = torch.device(a.device if (a.device != "cuda" or torch.cuda.is_available())
                       else "cpu")
    model = GLC_Image(inplace=True).to(dev)
    model.load_state_dict(get_state_dict(a.model), strict=True)
    model.eval()
    em = T.build_entropy_model(dev)
    print("设备: %s" % dev)

    pngs = sorted(f for f in os.listdir(a.png_dir) if f.lower().endswith(".png"))
    S = a.size
    files = sorted(f for f in os.listdir(a.glc_dir) if f.endswith(".glc"))
    rows = []

    for i, fn in enumerate(files[:a.n]):
        blob = open(os.path.join(a.glc_dir, fn), "rb").read()
        q_index, dims, streams = T.parse_bitstream(blob)
        (oh, ow, ph, pw, yc, yh, yw, zc, zh, zw, zcnt) = dims
        z_payload, *y_streams = streams
        od = os.path.join(a.ops_dir, "img%d" % i)

        t_all = time.perf_counter()
        z_indices = T.unpack_fixed_width(z_payload, zcnt, T.Z_INDEX_BITS)
        z_hat = model.z_vq.get_quan_feat(
            torch.tensor(z_indices, dtype=torch.long, device=dev).reshape(-1, 1),
            (1, zh, zw, zc))

        y_shape = (1, yc, yh, yw)
        masks = model.get_mask_four_parts(*y_shape, torch.float32, dev)
        y_hat_so_far = torch.zeros(y_shape, device=dev)

        t_ent = 0.0
        for stage, (mask, stream) in enumerate(zip(masks, y_streams)):
            s_raw = np.fromfile(os.path.join(od, "p%d_scales_raw.f32" % stage),
                                dtype=np.float32).reshape(y_shape)
            m_raw = np.fromfile(os.path.join(od, "p%d_means_raw.f32" % stage),
                                dtype=np.float32).reshape(y_shape)
            s_ = torch.from_numpy(s_raw).to(dev)
            m_ = torch.from_numpy(m_raw).to(dev)
            t0 = time.perf_counter()
            decoded = T.entropy_decode_stage(em, stream, s_, m_, mask)
            t_ent += time.perf_counter() - t0
            y_hat_so_far = y_hat_so_far + T.scatter_masked(decoded, mask, y_shape)

        # q_dec 由容器里的 z_hat 走模型得到（与编码端同一个函数）
        with torch.no_grad():
            params_pc = model.y_prior_fusion(model.hyper_dec(z_hat))
        _, q_dec, _, _, _ = T.split_common_params(model, params_pc)

        y_hat = y_hat_so_far * q_dec
        curr_q_dec = model.q_dec[q_index:q_index + 1]
        t0 = time.perf_counter()
        with torch.no_grad():
            rec = model.vqgan.generator(model.dec(y_hat, curr_q_dec)).clamp(-1, 1)
        if dev.type == "cuda":
            torch.cuda.synchronize(dev)
        t_s4 = time.perf_counter() - t0
        total = time.perf_counter() - t_all

        rec = rec[:, :, :oh, :ow]
        im = Image.open(os.path.join(a.png_dir, pngs[i % len(pngs)])).convert("RGB")
        w, h = im.size
        x0, y0 = (i * 37) % max(1, w - S), (i * 53) % max(1, h - S)
        px = np.asarray(im.crop((x0, y0, x0 + S, y0 + S)), dtype=np.float32) / 127.5 - 1.0
        x = torch.from_numpy(px.transpose(2, 0, 1)).unsqueeze(0).to(dev)

        rows.append(dict(glc=fn, bytes=len(blob), bpp=len(blob) * 8 / (S * S),
                         t_ent_ms=t_ent * 1000, t_s4_ms=t_s4 * 1000,
                         total_ms=total * 1000, psnr=psnr(rec, x.clamp(-1, 1))))
        r = rows[-1]
        print("  %-10s %4dB bpp=%.5f  熵解码=%5.1f  S4=%7.1f  合计=%7.1f ms  PSNR=%.2f"
              % (fn, r["bytes"], r["bpp"], r["t_ent_ms"], r["t_s4_ms"],
                 r["total_ms"], r["psnr"]))

    n = len(rows)
    agg = {k: sum(r[k] for r in rows) / n for k in
           ("bytes", "bpp", "t_ent_ms", "t_s4_ms", "total_ms", "psnr")}
    print("\n===== PC 解码板端码流（%s）平均 over %d =====" % (dev, n))
    print("  容器 %.1f B  bpp=%.5f  PSNR=%.2f" % (agg["bytes"], agg["bpp"], agg["psnr"]))
    print("  熵解码 %.1f ms + S4 %.1f ms = %.1f ms"
          % (agg["t_ent_ms"], agg["t_s4_ms"], agg["total_ms"]))
    if a.out:
        json.dump(dict(rows=rows, agg=agg, device=str(dev)),
                  open(a.out, "w"), indent=2, ensure_ascii=False)
        print("  报告:", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
