# -*- coding: utf-8 -*-
r"""按**子图/阶段**拆解的 PC 基准 —— 为了和板端 NPU 的数字同口径对比。

板端每个子图是独立的一趟 NPU 前向，所以 PC 侧也必须拆成同样的阶段：

    S1  <-> model.enc(model.vqgan.encoder(x)) + model.hyper_enc(y)
    S2  <-> model.y_prior_fusion(model.hyper_dec(z_hat))
    S3k <-> stage_parameters(model, k, ...)          (k=1,2,3)
    ent_enc  <-> entropy_encode_stage  x4  + z 的定长打包
    ent_dec  <-> entropy_decode_stage  x4  + z 的解包
    S4  <-> model.vqgan.generator(model.dec(y_hat, q_dec))

这样就能把 **板 NPU / 板 CPU / PC CPU / PC GPU** 放进同一张表。

用法（WSL Ubuntu-22.04）::
    python3 bench_pc_stages.py --device cuda --n 4
    python3 bench_pc_stages.py --device cpu  --n 4
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


class Timer:
    def __init__(self):
        self.acc = {}

    def add(self, k, v):
        self.acc[k] = self.acc.get(k, 0.0) + v


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

    def sync():
        if dev.type == "cuda":
            torch.cuda.synchronize(dev)

    def load(i):
        pngs = sorted(f for f in os.listdir(a.png_dir) if f.lower().endswith(".png"))
        im = Image.open(os.path.join(a.png_dir, pngs[i % len(pngs)])).convert("RGB")
        w, h = im.size
        x0, y0 = (i * 37) % max(1, w - a.size), (i * 53) % max(1, h - a.size)
        px = np.asarray(im.crop((x0, y0, x0 + a.size, y0 + a.size)),
                        dtype=np.float32) / 127.5 - 1.0
        x = torch.from_numpy(px.transpose(2, 0, 1)).unsqueeze(0).to(dev)
        return F.pad(x, GLC_Image.get_padding_size(a.size, a.size, 64), mode="replicate")

    def run(x):
        tm = Timer()
        S = a.size

        # ---------------- 编码 ----------------
        with torch.no_grad():
            t0 = time.perf_counter()
            y = model.enc(model.vqgan.encoder(x), model.q_enc[a.q:a.q + 1])
            z = model.hyper_enc(y)
            sync(); tm.add("s1", time.perf_counter() - t0)

            z_indices = model.z_vq.get_indices(z).reshape(-1).cpu().tolist()
            z_payload = T.pack_fixed_width(z_indices, T.Z_INDEX_BITS)
            z_hat = model.z_vq.get_quan_feat(
                torch.tensor(z_indices, dtype=torch.long, device=dev).reshape(-1, 1),
                (z.shape[0], z.shape[2], z.shape[3], z.shape[1]))

            t0 = time.perf_counter()
            params = model.y_prior_fusion(model.hyper_dec(z_hat))
            sync(); tm.add("s2", time.perf_counter() - t0)

            q_enc, q_dec, scales, means, common = T.split_common_params(model, params)
            y_scaled = y * q_enc
            masks = model.get_mask_four_parts(*y.shape, y.dtype, y.device)
            y_hat_so_far = torch.zeros_like(y)
            streams = []
            for stage, mask in enumerate(masks):
                if stage == 0:
                    s_, m_ = scales, means
                else:
                    t0 = time.perf_counter()
                    s_, m_ = T.stage_parameters(model, stage, y_hat_so_far,
                                                common, scales, means)
                    sync(); tm.add("s3p%d" % stage, time.perf_counter() - t0)
                t0 = time.perf_counter()
                stream, rec = T.entropy_encode_stage(em, y_scaled, s_, m_, mask)
                sync(); tm.add("ent_enc", time.perf_counter() - t0)
                streams.append(stream)
                y_hat_so_far = y_hat_so_far + T.scatter_masked(rec, mask, y.shape)
            header = T.HEADER.pack(
                T.MAGIC, T.VERSION, a.q, 0, S, S, x.shape[2], x.shape[3],
                y.shape[1], y.shape[2], y.shape[3], z.shape[1], z.shape[2], z.shape[3],
                len(z_indices), len(z_payload), *(len(s) for s in streams), 0)
            blob = header + z_payload + b"".join(streams)

            # ---------------- 解码 ----------------
            q_index, dims, ds = T.parse_bitstream(blob)
            (oh, ow, ph, pw, yc, yh, yw, zc, zh, zw, zcnt) = dims
            z_payload_d, *y_streams = ds
            zi = T.unpack_fixed_width(z_payload_d, zcnt, T.Z_INDEX_BITS)
            t0 = time.perf_counter()
            z_hat_d = model.z_vq.get_quan_feat(
                torch.tensor(zi, dtype=torch.long, device=dev).reshape(-1, 1),
                (1, zh, zw, zc))
            params_d = model.y_prior_fusion(model.hyper_dec(z_hat_d))
            _, q_dec_d, sc_d, mn_d, cm_d = T.split_common_params(model, params_d)
            sync(); tm.add("s2_dec", time.perf_counter() - t0)

            y_shape = (1, yc, yh, yw)
            y_hat_d = torch.zeros(y_shape, device=dev)
            for stage, (mask, st) in enumerate(zip(masks, y_streams)):
                if stage == 0:
                    s_, m_ = sc_d, mn_d
                else:
                    t0 = time.perf_counter()
                    s_, m_ = T.stage_parameters(model, stage, y_hat_d, cm_d, sc_d, mn_d)
                    sync(); tm.add("s3p%d_dec" % stage, time.perf_counter() - t0)
                t0 = time.perf_counter()
                dec = T.entropy_decode_stage(em, st, s_, m_, mask)
                sync(); tm.add("ent_dec", time.perf_counter() - t0)
                y_hat_d = y_hat_d + T.scatter_masked(dec, mask, y_shape)

            t0 = time.perf_counter()
            rec_img = model.vqgan.generator(
                model.dec(y_hat_d * q_dec_d, model.q_dec[q_index:q_index + 1])).clamp(-1, 1)
            sync(); tm.add("s4", time.perf_counter() - t0)

        rec_img = rec_img[:, :, :oh, :ow]
        return tm.acc, blob, rec_img

    for i in range(a.warmup):
        run(load(i))

    total = {}
    nb = 0
    pngs = sorted(f for f in os.listdir(a.png_dir) if f.lower().endswith(".png"))
    ps = []
    for i in range(a.n):
        x = load(i)
        acc, blob, rec = run(x)
        for k, v in acc.items():
            total[k] = total.get(k, 0.0) + v
        nb += len(blob)
        xc = x[:, :, :a.size, :a.size].clamp(-1, 1)
        ps.append(psnr(rec, xc))
        print("  图%d  S1=%.1f S2=%.1f S3=%.1f 熵编码=%.1f | 熵解码=%.1f S4=%.1f  合计=%.1f ms"
              % (i, acc["s1"] * 1000,
                 (acc["s2"] + acc.get("s2_dec", 0)) * 1000,
                 (acc.get("s3p1", 0) + acc.get("s3p2", 0) + acc.get("s3p3", 0)
                  + acc.get("s3p1_dec", 0) + acc.get("s3p2_dec", 0)
                  + acc.get("s3p3_dec", 0)) * 1000,
                 acc["ent_enc"] * 1000, acc["ent_dec"] * 1000, acc["s4"] * 1000,
                 sum(acc.values()) * 1000))

    n = a.n
    ms = {k: v / n * 1000 for k, v in total.items()}
    nn_enc = ms["s1"] + ms["s2"] + ms.get("s3p1", 0) + ms.get("s3p2", 0) + ms.get("s3p3", 0)
    nn_dec = ms.get("s2_dec", 0) + ms.get("s3p1_dec", 0) + ms.get("s3p2_dec", 0) + ms.get("s3p3_dec", 0)
    enc = nn_enc + ms["ent_enc"]
    dec = nn_dec + ms["ent_dec"] + ms["s4"]
    name = torch.cuda.get_device_name(0) if dev.type == "cuda" else "CPU"
    out = dict(device=str(dev), name=name, n=n,
               ms=ms, nn_enc=nn_enc, nn_dec=nn_dec, enc=enc, dec=dec, total=enc + dec,
               bpp=nb / n * 8 / (a.size * a.size), psnr=sum(ps) / n,
               bytes=nb / n)
    print("\n===== %s (%s) 平均 over %d =====" % (dev.type.upper(), name, n))
    for k in ("s1", "s2", "s3p1", "s3p2", "s3p3", "ent_enc",
              "s2_dec", "s3p1_dec", "s3p2_dec", "s3p3_dec", "ent_dec", "s4"):
        if k in ms:
            print("  %-10s %9.3f ms" % (k, ms[k]))
    print("  ---- 编码端 %.1f ms（NN %.1f + 熵编码 %.1f）"
          % (enc, nn_enc, ms["ent_enc"]))
    print("  ---- 解码端 %.1f ms（NN %.1f + 熵解码 %.1f + S4 %.1f）"
          % (dec, nn_dec, ms["ent_dec"], ms["s4"]))
    print("  ---- 合计   %.1f ms (%.2f fps)   bpp=%.5f  PSNR=%.2f"
          % (enc + dec, 1000.0 / (enc + dec), out["bpp"], out["psnr"]))
    if a.out:
        json.dump(out, open(a.out, "w"), indent=2, ensure_ascii=False)
        print("  报告:", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
