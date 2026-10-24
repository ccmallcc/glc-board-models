# -*- coding: utf-8 -*-
r"""PC 侧：解码板端码流并**把原图与重建图存成 PNG**（在 WSL Ubuntu-22.04 跑，
因为 compressai / torch 只在那儿装了）。

与 `pc_decode_board.py` 的关系：解码路径**完全一样**（同一套 `parse_bitstream` /
`entropy_decode_stage` / `GLC_Image`），唯一区别是**把图落盘**，便于肉眼比对。

裁剪口径与 `pc_decode_board.py` 一字不差（否则 PSNR 没法和历史数字对齐）：
    x0 = (i*37) % max(1, w-S)
    y0 = (i*53) % max(1, h-S)
    S  = 256
i=0 时是**左上角 256x256**。

用法::

    python3 pc_decode_vis.py \
        --glc_dir /mnt/e/fudanwei/工作区/_board_run/glc \
        --ops_dir /mnt/e/fudanwei/工作区/_board_run/e2e4/operands \
        --png_dir /mnt/e/fudanwei/工作区/testset/kodak_real \
        --out_dir /mnt/e/fudanwei/_logs/vis --n 4 --device cpu
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


def to_png(t_chw, path):
    """[-1,1] 的 CHW float tensor -> uint8 PNG"""
    a = t_chw.detach().cpu().numpy()
    a = np.clip((a + 1.0) * 127.5, 0, 255).astype(np.uint8)
    Image.fromarray(a.transpose(1, 2, 0)).save(path)


def side_by_side(orig_png, rec_png, path, label_h=0):
    a = Image.open(orig_png).convert("RGB")
    b = Image.open(rec_png).convert("RGB")
    w, h = a.size
    canvas = Image.new("RGB", (w * 2 + 8, h), (255, 255, 255))
    canvas.paste(a, (0, 0))
    canvas.paste(b, (w + 8, 0))
    canvas.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="/mnt/e/fudanwei/工作区/GLC-main/GLC-main")
    ap.add_argument("--model",
                    default="/mnt/e/fudanwei/工作区/GLC-main/GLC-main/pretrained/GLC_image.pth.tar")
    ap.add_argument("--glc_dir", required=True)
    ap.add_argument("--ops_dir", required=True)
    ap.add_argument("--png_dir", required=True)
    ap.add_argument("--out_dir", required=True)
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--json", default="")
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
    dev = torch.device(a.device if (a.device != "cuda" or torch.cuda.is_available()) else "cpu")
    model = GLC_Image(inplace=True).to(dev)
    model.load_state_dict(get_state_dict(a.model), strict=True)
    model.eval()
    em = T.build_entropy_model(dev)
    print("设备: %s" % dev)

    os.makedirs(a.out_dir, exist_ok=True)
    pngs = sorted(f for f in os.listdir(a.png_dir) if f.lower().endswith(".png"))
    files = sorted(f for f in os.listdir(a.glc_dir) if f.endswith(".glc"))
    S = a.size
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
        src_png = pngs[i % len(pngs)]
        im = Image.open(os.path.join(a.png_dir, src_png)).convert("RGB")
        w, h = im.size
        x0, y0 = (i * 37) % max(1, w - S), (i * 53) % max(1, h - S)
        crop = im.crop((x0, y0, x0 + S, y0 + S))
        px = np.asarray(crop, dtype=np.float32) / 127.5 - 1.0
        x = torch.from_numpy(px.transpose(2, 0, 1)).unsqueeze(0).to(dev)

        op = os.path.join(a.out_dir, "orig_img%d.png" % i)
        rp = os.path.join(a.out_dir, "rec_img%d.png" % i)
        sp = os.path.join(a.out_dir, "side_img%d.png" % i)
        crop.save(op)
        to_png(rec[0], rp)
        side_by_side(op, rp, sp)

        p = psnr(rec, x.clamp(-1, 1))
        rows.append(dict(glc=fn, source=src_png, crop=[x0, y0, S, S],
                         bytes=len(blob), bpp=len(blob) * 8 / (S * S),
                         t_ent_ms=t_ent * 1000, t_s4_ms=t_s4 * 1000,
                         total_ms=total * 1000, psnr=p,
                         orig_png=op, rec_png=rp, side_png=sp))
        print("  %-10s %-14s 裁剪(%d,%d)  %4dB bpp=%.5f  熵解码=%5.1f S4=%7.1f 合计=%7.1f ms  PSNR=%.2f dB"
              % (fn, src_png, x0, y0, len(blob), rows[-1]["bpp"],
                 rows[-1]["t_ent_ms"], rows[-1]["t_s4_ms"], rows[-1]["total_ms"], p))
        print("       原图 %s\n       重建 %s\n       并排 %s" % (op, rp, sp))

    n = len(rows)
    if n:
        agg = {k: sum(r[k] for r in rows) / n
               for k in ("bytes", "bpp", "t_ent_ms", "t_s4_ms", "total_ms", "psnr")}
        print("\n===== PC 解码板端码流并出图（%s）平均 over %d =====" % (dev, n))
        print("  容器 %.1f B  bpp=%.5f  PSNR=%.2f dB" % (agg["bytes"], agg["bpp"], agg["psnr"]))
        print("  熵解码 %.1f ms + S4 %.1f ms = %.1f ms"
              % (agg["t_ent_ms"], agg["t_s4_ms"], agg["total_ms"]))
        if a.json:
            json.dump(dict(rows=rows, agg=agg, device=str(dev)),
                      open(a.json, "w"), indent=2, ensure_ascii=False)
            print("  报告:", a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
