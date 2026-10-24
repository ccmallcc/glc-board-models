# -*- coding: utf-8 -*-
r"""V6: full Kodak baseline with the REAL bitstream, and an independent check of
the team's "+4~6% bitrate overhead vs the theoretical estimate" claim.

For every image and every q index we measure BOTH:

  theoretical  model.test(x, q) -> bit_y (Gaussian cross-entropy) + bit_z
               where bit_z = positions * log2(codebook_size), and
               codebook_size = 16384 so log2 == 14 == Z_INDEX_BITS.
               NOTE: this estimate contains NO container header.

  real         test_image_complement2.compress_glc -> the actual .glc bytes,
               split into header (76 B) + z segment + four y streams.

overhead = real/theoretical - 1, reported both including and excluding the
header, so the two sources of overhead are separated.

Usage (WSL, needs model + compressai):
  python v6_kodak_baseline.py --model_path <ckpt> --input_path <kodak> --out <dir>
"""
import argparse
import csv
import json
import math
import os
import sys
import time
import types

import numpy as np
import torch
import torch.nn.functional as F


def psnr(a, b):
    """a, b in [-1, 1]."""
    mse = float(((a - b) ** 2).mean())
    return 99.0 if mse == 0 else 10.0 * math.log10(4.0 / mse)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=r"E:\fudanwei\工作区\GLC-main\GLC-main")
    ap.add_argument("--model_path", required=True)
    ap.add_argument("--input_path", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--q", type=int, nargs="+", default=[0, 1, 2, 3])
    ap.add_argument("--limit", type=int, default=0, help="0 = all images")
    ap.add_argument("--crop", type=int, default=0,
                    help=">0: deterministic SxS crop instead of the whole image")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--save_png", action="store_true")
    a = ap.parse_args()

    repo = os.path.abspath(a.repo)
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "src", "utils"))
    # stub the metric module (lpips/DISTS/FID); V7 measures perceptual quality
    stub = types.ModuleType("src.utils.metric_image")
    stub.evaluate_quality = lambda *x, **k: None
    sys.modules["src.utils.metric_image"] = stub

    from torch.utils.data import DataLoader
    import test_image_complement2 as T
    from src.models.image_model import GLC_Image
    from src.utils.test_utils import (
        OnlyImageFolder, from_0_1_to_minus1_1, get_state_dict, init_func,
        write_image,
    )

    init_func()
    dev = torch.device(a.device if torch.cuda.is_available() else "cpu")
    model = GLC_Image(inplace=True).to(dev)
    model.load_state_dict(get_state_dict(a.model_path), strict=True)
    model.eval()
    em = T.build_entropy_model(dev)
    T.validate_entropy_codec(em, dev)
    print("device=%s  codebook_size=%d  log2=%d  Z_INDEX_BITS=%d  HEADER.size=%d"
          % (dev, model.codebook_size, int(math.log2(model.codebook_size)),
             T.Z_INDEX_BITS, T.HEADER.size))
    assert int(math.log2(model.codebook_size)) == T.Z_INDEX_BITS, \
        "theoretical z-bit estimate and the real fixed-width packing disagree"

    ds = OnlyImageFolder(a.input_path, padding_size=64)
    loader = DataLoader(ds, batch_size=1, num_workers=0, shuffle=False)
    n_img = len(ds) if a.limit <= 0 else min(a.limit, len(ds))
    os.makedirs(a.out, exist_ok=True)

    rows = []
    for q in a.q:
        qdir = os.path.join(a.out, "q%d" % q)
        os.makedirs(qdir, exist_ok=True)
        acc = {"th_bit_y": 0.0, "th_bit_z": 0.0, "real_tot": 0, "real_y": 0,
               "real_z": 0, "hdr": 0, "px": 0, "psnr": 0.0, "enc": 0.0, "dec": 0.0}
        for i, (image, image_path) in enumerate(loader):
            if i >= n_img:
                break
            x = from_0_1_to_minus1_1(image.to(dev))
            if a.crop > 0:
                _, _, H, W = x.shape
                if H < a.crop or W < a.crop:
                    print("  [skip] %s is %dx%d, smaller than the %d crop"
                          % (os.path.basename(image_path[0]), W, H, a.crop))
                    continue
                cy = (i * 53) % max(1, H - a.crop)
                cx = (i * 37) % max(1, W - a.crop)
                x = x[:, :, cy:cy + a.crop, cx:cx + a.crop].contiguous()
            height, width = x.shape[-2:]
            padding = GLC_Image.get_padding_size(height, width, 64)
            x_padded = F.pad(x, padding, mode="replicate")
            name = os.path.splitext(os.path.basename(image_path[0]))[0]
            px = height * width

            with torch.no_grad():
                t0 = time.perf_counter()
                th = model.test(x_padded, q)
                t1 = time.perf_counter()
                container, enc_yhat = T.compress_glc(
                    model, em, x_padded, q, (height, width))
                t2 = time.perf_counter()
                x_hat, _ = T.decompress_glc(model, em, container)
                t3 = time.perf_counter()

            q_index, dims, streams = T.parse_bitstream(container)
            assert q_index == q
            z_b = len(streams[0]); y_b = sum(len(s) for s in streams[1:])
            hdr_b = T.HEADER.size
            assert hdr_b + z_b + y_b == len(container)

            p = psnr(x.detach().cpu(), x_hat.detach().cpu())
            th_y = th["bit_y"]; th_z = th["bit_z"]
            real_bits = len(container) * 8.0
            row = {
                "q": q, "image": name, "h": height, "w": width,
                "pad_h": dims[2], "pad_w": dims[3],
                "z_count": dims[10],
                "th_bit_y": th_y, "th_bit_z": th_z, "th_bits": th_y + th_z,
                "th_bpp": (th_y + th_z) / px,
                "th_bpp_y": th_y / px, "th_bpp_z": th_z / px,
                "real_bytes": len(container),
                "real_bpp": real_bits / px,
                "real_bpp_y": y_b * 8.0 / px,
                "real_bpp_z": z_b * 8.0 / px,
                "real_bpp_header": hdr_b * 8.0 / px,
                "hdr_bytes": hdr_b, "y_bytes": y_b, "z_bytes": z_b,
                "overhead_pct": 100.0 * ((th_y + th_z) and
                                         (real_bits / (th_y + th_z) - 1.0)),
                "overhead_nohdr_pct": 100.0 * ((th_y + th_z) and
                                               ((len(container) - hdr_b) * 8.0 /
                                                (th_y + th_z) - 1.0)),
                "psnr": p,
                "enc_s": t2 - t1, "dec_s": t3 - t2, "theory_s": t1 - t0,
            }
            rows.append(row)
            acc["th_bit_y"] += th_y; acc["th_bit_z"] += th_z
            acc["real_tot"] += len(container); acc["real_y"] += y_b
            acc["real_z"] += z_b; acc["hdr"] += hdr_b; acc["px"] += px
            acc["psnr"] += p; acc["enc"] += row["enc_s"]; acc["dec"] += row["dec_s"]
            print("[q%d %2d/%2d %-10s %4dx%-4d] th=%.5f real=%.5f "
                  "ovh=%+6.2f%% (no-hdr %+6.2f%%) psnr=%.2f hdr=%dB"
                  % (q, i + 1, n_img, name, width, height, row["th_bpp"],
                     row["real_bpp"], row["overhead_pct"],
                     row["overhead_nohdr_pct"], p, hdr_b))

            if a.save_png:
                write_image(os.path.join(qdir, name + ".png"), x_hat)

        th_bits = acc["th_bit_y"] + acc["th_bit_z"]
        real_bits = acc["real_tot"] * 8.0
        summary = {
            "q": q, "n": n_img,
            "th_bpp": th_bits / acc["px"], "real_bpp": real_bits / acc["px"],
            "overhead_pct": 100.0 * (real_bits / th_bits - 1.0),
            "overhead_nohdr_pct": 100.0 * ((acc["real_tot"] - acc["hdr"]) * 8.0 / th_bits - 1.0),
            "hdr_bpp": acc["hdr"] * 8.0 / acc["px"],
            "y_bpp": acc["real_y"] * 8.0 / acc["px"],
            "z_bpp": acc["real_z"] * 8.0 / acc["px"],
            "psnr": acc["psnr"] / n_img,
            "enc_s": acc["enc"] / n_img, "dec_s": acc["dec"] / n_img,
        }
        print("  AVERAGE q%d: th=%.6f real=%.6f overhead=%+.2f%% "
              "(excluding the %d B header: %+.2f%%) psnr=%.3f enc=%.3fs dec=%.3fs"
              % (q, summary["th_bpp"], summary["real_bpp"],
                 summary["overhead_pct"], T.HEADER.size,
                 summary["overhead_nohdr_pct"], summary["psnr"],
                 summary["enc_s"], summary["dec_s"]))
        rows.append(dict(summary, image="AVERAGE"))

        # CSV: per-image rows for this q, then the average row (missing columns
        # filled with "" so the writer never sees an unknown key)
        per_image = [r for r in rows if r["q"] == q and r["image"] != "AVERAGE"]
        cols = list(per_image[0].keys())
        avg_row = {k: summary.get(k, "") for k in cols}
        avg_row["image"] = "AVERAGE"
        with open(os.path.join(qdir, "compression_metrics.csv"), "w",
                  newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in per_image:
                w.writerow(r)
            w.writerow(avg_row)

    json.dump(rows, open(os.path.join(a.out, "v6_baseline.json"), "w",
                         encoding="utf-8"), ensure_ascii=False, indent=2)
    print("\n  -> %s" % os.path.join(a.out, "v6_baseline.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
