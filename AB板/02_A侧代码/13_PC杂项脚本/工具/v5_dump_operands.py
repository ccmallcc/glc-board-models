# -*- coding: utf-8 -*-
r"""V5 step 1: run the team's own codec on real images and dump everything the
board needs to rebuild the GLC2 container *without* the model.

We monkeypatch `test_image_complement2.entropy_encode_stage`, so the operands we
capture are by construction exactly the ones the real codec handed to
compressai -- no reimplementation, no drift.

Per image we write (into --out\img{i}\):

    hdr.txt           all 21 header fields, human readable
    p{k}_sym.i32      int32 symbols  = round(values - means)      (16384 each)
    p{k}_scales.f32   float32 scales = compacted, clamped >= 0.11
    p{k}_resid.f32    float32 (values - means) before rounding, for the
                      round-half-to-even analysis
    z_indices.i32     int32 VQ indices for z
    ref.glc           the team's own container (byte reference)
    ref_recon.f32     reference reconstruction (padded, then cropped)
    ref_yhat.f32      reference y_hat
    stats.json        half-integer counts, sizes, md5s

Usage (in envs\glc, cwd = GLC repo root):
  python v5_dump_operands.py --model_path pretrained/GLC_image.pth.tar \
      --input_path E:\fudanwei\工作区\testset\kodak \
      --out E:\fudanwei\工作区\v5 --n 2 --q 0
"""
import argparse
import hashlib
import json
import os
import struct
import sys

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=r"E:\fudanwei\工作区\GLC-main\GLC-main")
    ap.add_argument("--model_path", required=True)
    ap.add_argument("--input_path", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=2)
    ap.add_argument("--q", type=int, default=0)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--crop", type=int, default=0,
                    help=">0: use deterministic SxS crops of the Kodak images "
                         "instead of whole images (matches dump_entropy_operands.py)")
    a = ap.parse_args()

    repo = os.path.abspath(a.repo)
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "src", "utils"))

    # `test_image_complement2` pulls in `src.utils.metric_image` at import time,
    # which drags in lpips / DISTS_pytorch / pytorch_msssim / torchmetrics.FID.
    # None of that is needed to exercise the *codec*, and `evaluate_quality` is
    # only called from the team's main().  Stub just that one module so the
    # codec itself is imported verbatim -- we change nothing else.
    import types
    stub = types.ModuleType("src.utils.metric_image")
    def _unused_evaluate_quality(*args, **kwargs):
        raise RuntimeError("v5_dump_operands does not evaluate quality metrics")
    stub.evaluate_quality = _unused_evaluate_quality
    sys.modules["src.utils.metric_image"] = stub

    import torch.nn.functional as F
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
    T.validate_entropy_codec(em, dev)
    print("entropy codec self-test passed on %s" % dev)

    # ---- capture the exact operands the codec feeds to compressai -----------
    cap = {}
    orig_stage = T.entropy_encode_stage

    def hooked_stage(entropy_model, y_scaled, scales, means, mask):
        # reproduce exactly what orig_stage computes for the payload
        y_values = T.compact_masked(y_scaled, mask)
        stage_scales = T.compact_masked(scales, mask).clamp_min(T.SCALE_MIN)
        stage_means = T.compact_masked(means, mask)
        idx = entropy_model.build_indexes(stage_scales)
        resid = (y_values - stage_means).reshape(-1)
        sym = torch.round(resid)
        cap.setdefault("phases", []).append({
            "sym": sym.to(torch.int32).reshape(-1).cpu().numpy().copy(),
            "scales": stage_scales.reshape(-1).to(torch.float32).cpu().numpy().copy(),
            "resid": resid.to(torch.float32).cpu().numpy().copy(),
            "indexes": idx.reshape(-1).to(torch.int64).cpu().numpy().copy(),
        })
        payload, recon = orig_stage(entropy_model, y_scaled, scales, means, mask)
        # cross-check: our recomputation must round-trip identically
        assert torch.equal(sym.to(torch.int64).reshape(-1),
                           entropy_model.model.quantize(
                               y_values, "symbols", stage_means).reshape(-1).to(torch.int64)), \
            "captured symbols disagree with compressai's own quantize()"
        return payload, recon

    T.entropy_encode_stage = hooked_stage

    orig_pack = T.pack_fixed_width

    def hooked_pack(values, bit_width):
        out = orig_pack(values, bit_width)
        if bit_width == T.Z_INDEX_BITS:
            cap["z"] = [int(v) for v in values]
        return out

    T.pack_fixed_width = hooked_pack

    ds = OnlyImageFolder(a.input_path, padding_size=64)
    loader = DataLoader(ds, batch_size=1, num_workers=0, shuffle=False)
    os.makedirs(a.out, exist_ok=True)

    for i, (image, image_path) in enumerate(loader):
        if i >= a.n:
            break
        cap["phases"] = []
        x = from_0_1_to_minus1_1(image.to(dev))
        if a.crop > 0:
            # deterministic crop, identical to dump_entropy_operands.py so the
            # results line up with the earlier entropy_ops/img{i} dumps
            S = a.crop
            _, _, H, W = x.shape
            y0 = (i * 53) % max(1, H - S)
            x0 = (i * 37) % max(1, W - S)
            x = x[:, :, y0:y0 + S, x0:x0 + S].contiguous()
        height, width = x.shape[-2:]
        padding = GLC_Image.get_padding_size(height, width, 64)
        x_padded = F.pad(x, padding, mode="replicate")

        container, _ = T.compress_glc(model, em, x_padded, a.q, (height, width))
        q_index, dims, streams = T.parse_bitstream(container)
        (oh, ow, ph, pw, yc, yh, yw, zc, zh, zw, zcnt) = dims

        with torch.no_grad():
            recon, y_hat = T.decompress_glc(model, em, container)

        od = os.path.join(a.out, "img%d" % i)
        os.makedirs(od, exist_ok=True)
        name = os.path.basename(image_path[0])

        half = []
        for k, rec in enumerate(cap["phases"]):
            rec["sym"].astype(np.int32).tofile(os.path.join(od, "p%d_sym.i32" % k))
            rec["scales"].astype(np.float32).tofile(os.path.join(od, "p%d_scales.f32" % k))
            rec["resid"].astype(np.float32).tofile(os.path.join(od, "p%d_resid.f32" % k))
            # round-half cases: x.5 exactly
            r = torch.from_numpy(rec["resid"])
            is_half = (torch.abs(r - torch.floor(r) - 0.5) < 1e-6)
            nh = int(is_half.sum().item())
            # what C's round-half-away-from-zero would give, vs torch's half-to-even
            away = np.floor(np.abs(rec["resid"]) + 0.5) * np.sign(rec["resid"])
            away = away.astype(np.int32)
            ndiff = int((away != rec["sym"]).sum())
            # scales must be inside the 64-level table range
            smin, smax = float(rec["scales"].min()), float(rec["scales"].max())
            half.append({"phase": k, "n": int(rec["sym"].size),
                         "exact_half": nh, "roundmode_diff": ndiff,
                         "scale_min": smin, "scale_max": smax,
                         "sym_min": int(rec["sym"].min()),
                         "sym_max": int(rec["sym"].max()),
                         "resid_absmax": float(np.abs(rec["resid"]).max()),
                         "cdf_rows": int(len(set(rec["indexes"].tolist())))})
            print("    phase %d: n=%d exact_half=%d roundmode_diff=%d "
                  "sym[%d,%d] scale[%.4f,%.4f] rows=%d"
                  % (k, rec["sym"].size, nh, ndiff,
                     rec["sym"].min(), rec["sym"].max(), smin, smax,
                     half[-1]["cdf_rows"]))

        z = np.array(cap.get("z", []), dtype=np.int32)
        z.tofile(os.path.join(od, "z_indices.i32"))

        recon.detach().cpu().numpy().astype(np.float32).tofile(
            os.path.join(od, "ref_recon.f32"))
        y_hat.detach().cpu().numpy().astype(np.float32).tofile(
            os.path.join(od, "ref_yhat.f32"))
        with open(os.path.join(od, "ref.glc"), "wb") as f:
            f.write(container)

        with open(os.path.join(od, "hdr.txt"), "w", encoding="utf-8") as f:
            f.write("# GLC2 header fields for img%d (%s)\n" % (i, name))
            f.write("MAGIC GLC2\n")
            f.write("VERSION %d\n" % T.VERSION)
            f.write("Q_INDEX %d\n" % q_index)
            f.write("FLAGS 0\n")
            f.write("ORIG_H %d\n" % oh)
            f.write("ORIG_W %d\n" % ow)
            f.write("PAD_H %d\n" % ph)
            f.write("PAD_W %d\n" % pw)
            f.write("Y_C %d\n" % yc)
            f.write("Y_H %d\n" % yh)
            f.write("Y_W %d\n" % yw)
            f.write("Z_C %d\n" % zc)
            f.write("Z_H %d\n" % zh)
            f.write("Z_W %d\n" % zw)
            f.write("Z_COUNT %d\n" % zcnt)
            f.write("Z_BYTES %d\n" % len(streams[0]))
            for k in range(4):
                f.write("STAGE%d_LEN %d\n" % (k, len(streams[k + 1])))
            f.write("TRAILER 0\n")
            f.write("RECON_H %d\n" % recon.shape[-2])
            f.write("RECON_W %d\n" % recon.shape[-1])
            f.write("REF_MD5 %s\n" % hashlib.md5(container).hexdigest())
            f.write("REF_BYTES %d\n" % len(container))
            f.write("SOURCE %s\n" % name)

        print("  img%d %s  %dx%d -> padded %dx%d  y=(%d,%d,%d) z=(%d,%d,%d) "
              "container %d B  md5=%s"
              % (i, name, oh, ow, ph, pw, yc, yh, yw, zc, zh, zw, len(container),
                 hashlib.md5(container).hexdigest()[:12]))
        json.dump({"image": name, "q_index": q_index, "container_bytes": len(container),
                   "container_md5": hashlib.md5(container).hexdigest(),
                   "dims": {"orig": [oh, ow], "padded": [ph, pw],
                            "y": [yc, yh, yw], "z": [zc, zh, zw], "z_count": zcnt},
                   "stage_bytes": [len(s) for s in streams[1:]],
                   "z_bytes": len(streams[0]), "phases": half},
                  open(os.path.join(od, "stats.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)

    print("\n  -> %s" % os.path.abspath(a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
