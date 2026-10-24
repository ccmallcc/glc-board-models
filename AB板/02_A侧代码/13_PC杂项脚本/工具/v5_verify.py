# -*- coding: utf-8 -*-
r"""V5 step 4: decode the containers WE produced (board path) with the stock
compressai/team decoder and confirm the reconstruction is identical to the
reference, plus report PSNR against the original crop.

Also re-runs the independent container validator's logic is left to
glc2_validate.py; this script is about the decode end.

Usage (WSL or envs\glc):
  python v5_verify.py --repo <GLC> --model_path <ckpt> --input_path <kodak> \
      --v5 <v5 dir> --n 4 --crop 256
"""
import argparse
import hashlib
import json
import math
import os
import sys
import types

import numpy as np
import torch


def psnr(a, b):
    mse = float(((a - b) ** 2).mean())
    return 99.0 if mse == 0 else 10.0 * math.log10(4.0 / mse)  # a,b in [-1,1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=r"E:\fudanwei\工作区\GLC-main\GLC-main")
    ap.add_argument("--model_path", required=True)
    ap.add_argument("--input_path", required=True)
    ap.add_argument("--v5", required=True)
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--crop", type=int, default=256)
    ap.add_argument("--device", default="cuda")
    a = ap.parse_args()

    repo = os.path.abspath(a.repo)
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "src", "utils"))

    stub = types.ModuleType("src.utils.metric_image")
    stub.evaluate_quality = lambda *x, **k: (_ for _ in ()).throw(
        RuntimeError("not used in V5"))
    sys.modules["src.utils.metric_image"] = stub

    from torch.utils.data import DataLoader
    import test_image_complement2 as T
    from src.models.image_model import GLC_Image
    from src.utils.test_utils import (
        OnlyImageFolder, from_0_1_to_minus1_1, get_state_dict, init_func,
    )

    init_func()
    dev = torch.device(a.device if torch.cuda.is_available() else "cpu")
    model = GLC_Image(inplace=True).to(dev)
    model.load_state_dict(get_state_dict(a.model_path), strict=True)
    model.eval()
    em = T.build_entropy_model(dev)

    ds = OnlyImageFolder(a.input_path, padding_size=64)
    loader = DataLoader(ds, batch_size=1, num_workers=0, shuffle=False)

    rows, all_ok = [], True
    for i, (image, image_path) in enumerate(loader):
        if i >= a.n:
            break
        od = os.path.join(a.v5, "img%d" % i)
        board = open(os.path.join(od, "board.glc"), "rb").read()
        ref = open(os.path.join(od, "ref.glc"), "rb").read()

        x = from_0_1_to_minus1_1(image.to(dev))
        if a.crop > 0:
            _, _, H, W = x.shape
            y0 = (i * 53) % max(1, H - a.crop)
            x0 = (i * 37) % max(1, W - a.crop)
            xc = x[:, :, y0:y0 + a.crop, x0:x0 + a.crop].contiguous()
        else:
            xc = x.contiguous()

        with torch.no_grad():
            rec_board, yhat_board = T.decompress_glc(model, em, board)
            rec_ref, yhat_ref = T.decompress_glc(model, em, ref)

        ref_stored = np.fromfile(os.path.join(od, "ref_recon.f32"),
                                 dtype=np.float32).reshape(rec_ref.shape)
        same_container = (board == ref)
        same_recon = bool(torch.equal(rec_board, rec_ref))
        same_yhat = bool(torch.equal(yhat_board, yhat_ref))
        same_as_stored = bool(np.array_equal(
            rec_board.detach().cpu().numpy(), ref_stored))
        p = psnr(xc.detach().cpu(), rec_board.detach().cpu())
        hdr = dict(l.split(" ", 1) for l in
                   open(os.path.join(od, "hdr.txt"), encoding="utf-8").read().splitlines()
                   if l and not l.startswith("#"))
        rows.append(dict(img=i, image=hdr["SOURCE"] if False else hdr.get("SOURCE", ""),
                         bytes=len(board), md5=hashlib.md5(board).hexdigest(),
                         same_container=same_container, same_recon=same_recon,
                         same_yhat=same_yhat, same_as_stored=same_as_stored,
                         psnr=round(p, 4)))
        ok = same_container and same_recon and same_yhat and same_as_stored
        all_ok &= ok
        print("img%d %-12s %4d B  md5=%s" % (i, rows[-1]["image"], len(board),
                                             rows[-1]["md5"][:12]))
        print("      容器 == 参考容器        : %s" % ("✅" if same_container else "❌"))
        print("      解码重建 == 参考重建    : %s" % ("✅" if same_recon else "❌"))
        print("      解码 y_hat == 参考 y_hat: %s" % ("✅" if same_yhat else "❌"))
        print("      重建 == 落盘参考重建    : %s" % ("✅" if same_as_stored else "❌"))
        print("      PSNR vs 原图            : %.4f dB" % p)

    print("\n" + "=" * 60)
    if all_ok:
        print("V5 结论：自产容器 → 独立校验 → compressai 解码 → 重建，全链路闭合 ✅")
    else:
        print("V5 结论：存在失败 ❌")
    json.dump({"rows": rows, "all_ok": bool(all_ok)},
              open(os.path.join(a.v5, "v5_verify.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
