# -*- coding: utf-8 -*-
r"""V3: a self-contained regression vector set for the whole bitstream path.

WHY NOT THE TEAM'S .glc FILES
-----------------------------
The obvious source of vectors would be the team's own 224 containers.  They do
pass container-format validation (224/224, see reports\GLC2比特流格式校验报告.md),
but they **cannot be decoded by the code shipped in the same repository** --
decoding yields all-NaN.  A container produced by the current code decodes
perfectly, and the mismatch is not the checkpoint, the attention rewrite, or the
q index (all tested; see reports\V3_回归向量集报告.md).  So they are usable as
*format-level* vectors only.

This script therefore builds the regression set from containers WE produce,
which is what a regression set should be anyway: fully reproducible, with a
golden value for every stage of the path.

    # create the golden set (needs model + compressai)
    python v3_regression.py --make
    # re-run and check (exit 0 = everything reproduced)
    python v3_regression.py --run

A vector pins down, for a fixed (image crop, q):
    * container md5          (encoding: masks, CDF indexes, rANS, header, packing)
    * reconstruction pixels  (decoding: parse, entropy decode, latent bookkeeping,
                              generator)
"""
import argparse
import glob
import hashlib
import json
import os
import sys
import types

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image


def crop_of(png, i, S):
    im = Image.open(png).convert("RGB")
    w, h = im.size
    if w < S or h < S:
        return None
    x0 = (i * 37) % max(1, w - S)
    y0 = (i * 53) % max(1, h - S)
    px = np.asarray(im.crop((x0, y0, x0 + S, y0 + S)), dtype=np.float32) / 127.5 - 1.0
    return torch.from_numpy(px.transpose(2, 0, 1)).unsqueeze(0).contiguous()


def load_env(a):
    repo = os.path.abspath(a.repo)
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "src", "utils"))
    stub = types.ModuleType("src.utils.metric_image")
    stub.evaluate_quality = lambda *x, **k: None
    sys.modules["src.utils.metric_image"] = stub
    import test_image_complement2 as T
    from src.models.image_model import GLC_Image
    from src.utils.test_utils import get_state_dict, init_func, write_image
    init_func()
    dev = torch.device(a.device if torch.cuda.is_available() else "cpu")
    model = GLC_Image(inplace=True).to(dev)
    model.load_state_dict(get_state_dict(a.model_path), strict=True)
    model.eval()
    return T, model, T.build_entropy_model(dev), dev, write_image


def psnr(a, b):
    mse = float(((a - b) ** 2).mean())
    return 99.0 if mse == 0 else 10.0 * np.log10(4.0 / mse)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=r"E:\fudanwei\工作区\GLC-main\GLC-main")
    ap.add_argument("--model_path",
                    default=r"E:\fudanwei\工作区\GLC-main\GLC-main\pretrained\GLC_image.pth.tar")
    ap.add_argument("--png_dir", default=r"E:\fudanwei\工作区\testset\kodak_real")
    ap.add_argument("--out", default=r"E:\fudanwei\工作区\v3")
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--q", type=int, nargs="+", default=[0, 1, 2, 3])
    ap.add_argument("--v5_dirs", nargs="*", default=[])
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--make", action="store_true")
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()
    if not (a.make or a.run):
        a.make = a.run = True

    T, model, em, dev, write_image = load_env(a)
    gold = os.path.join(a.out, "golden")
    os.makedirs(gold, exist_ok=True)
    pngs = sorted(glob.glob(os.path.join(a.png_dir, "*.png")))[:a.n]
    man_path = os.path.join(a.out, "v3_manifest.json")

    # ---------------- make ----------------
    if a.make:
        vecs = []
        for i, png in enumerate(pngs):
            x = crop_of(png, i, a.size)
            if x is None:
                continue
            x = x.to(dev)
            for q in a.q:
                name = "%s_q%d" % (os.path.splitext(os.path.basename(png))[0], q)
                with torch.no_grad():
                    container, enc_yhat = T.compress_glc(model, em, x, q,
                                                         (a.size, a.size))
                    dec, dec_yhat = T.decompress_glc(model, em, container)
                gp = os.path.join(gold, name + ".glc")
                open(gp, "wb").write(container)
                write_image(os.path.join(gold, name + "_recon.png"), dec)
                latent_ok = bool(torch.equal(enc_yhat, dec_yhat))
                vecs.append({
                    "name": name, "q": q, "png": os.path.abspath(png), "idx": i,
                    "size": a.size,
                    "glc": os.path.relpath(gp, a.out).replace("\\", "/"),
                    "glc_md5": hashlib.md5(container).hexdigest(),
                    "glc_bytes": len(container),
                    "recon_sha": hashlib.sha256(
                        open(os.path.join(gold, name + "_recon.png"), "rb").read()
                    ).hexdigest(),
                    "psnr_vs_src": round(psnr(dec, x), 4),
                    "latent_roundtrip_exact": latent_ok,
                })
                print("  make %-18s %5d B  psnr=%.2f  latent_exact=%s"
                      % (name, len(container), psnr(dec, x), latent_ok))
        # our board-produced containers (V5) as decode-only vectors
        for d in a.v5_dirs:
            for g in sorted(glob.glob(os.path.join(d, "img*", "board.glc"))):
                rf = os.path.join(os.path.dirname(g), "ref_recon.f32")
                if not os.path.exists(rf):
                    continue
                vecs.append({
                    "name": "v5_" + os.path.basename(os.path.dirname(g)),
                    "q": -1, "png": "", "idx": -1, "size": 0,
                    "glc": os.path.abspath(g).replace("\\", "/"),
                    "glc_md5": hashlib.md5(open(g, "rb").read()).hexdigest(),
                    "glc_bytes": os.path.getsize(g),
                    "ref_f32": os.path.abspath(rf).replace("\\", "/"),
                })
        json.dump({"vectors": vecs}, open(man_path, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print("golden set: %d vectors -> %s" % (len(vecs), man_path))
        for v in vecs:
            if not v.get("latent_roundtrip_exact", True):
                print("  !! %s: encoder/decoder y_hat differ" % v["name"])

    # ---------------- run ----------------
    if a.run:
        man = json.load(open(man_path, encoding="utf-8"))
        vecs = man["vectors"]
        tmp = os.path.join(a.out, "_tmp.png")
        nfail = 0
        rows = []
        for k, v in enumerate(vecs):
            gp = v["glc"] if os.path.isabs(v["glc"]) else os.path.join(a.out, v["glc"])
            blob = open(gp, "rb").read()
            md5_ok = hashlib.md5(blob).hexdigest() == v["glc_md5"]
            with torch.no_grad():
                # if this vector has a source image, also re-encode and compare
                enc_ok = None
                if v["png"]:
                    x = crop_of(v["png"], v["idx"], v["size"]).to(dev)
                    container, _ = T.compress_glc(model, em, x, v["q"],
                                                  (v["size"], v["size"]))
                    enc_ok = hashlib.md5(container).hexdigest() == v["glc_md5"]
                dec, _ = T.decompress_glc(model, em, blob)
            if "ref_f32" in v:
                ref = np.fromfile(v["ref_f32"], dtype=np.float32).reshape(dec.shape)
                ref_img = np.clip(np.rint(np.clip((ref[0] + 1) * 0.5, 0, 1) * 255),
                                  0, 255).astype(np.uint8).transpose(1, 2, 0)
                write_image(tmp, dec)
                got = np.asarray(Image.open(tmp).convert("RGB"))
                px_ok = got.shape == ref_img.shape and bool((got == ref_img).all())
                ndiff = int((got != ref_img).sum()) if got.shape == ref_img.shape else -1
            else:
                sha = hashlib.sha256(
                    open(os.path.join(gold, v["name"] + "_recon.png"), "rb").read()
                ).hexdigest()
                write_image(tmp, dec)
                sha2 = hashlib.sha256(open(tmp, "rb").read()).hexdigest()
                px_ok = (sha == sha2)
                ndiff = 0 if px_ok else -1
            ok = md5_ok and px_ok and (enc_ok is not False)
            nfail += 0 if ok else 1
            rows.append(dict(v, status="ok" if ok else "FAIL", md5_ok=md5_ok,
                             enc_ok=enc_ok, px_ok=px_ok, px_diff=ndiff))
            print("  [%2d/%2d] %-22s %s  enc=%s  dec_px=%s"
                  % (k + 1, len(vecs), v["name"], "OK " if ok else "FAIL",
                     {True: "ok", False: "CHANGED", None: "n/a"}[enc_ok],
                     "ok" if px_ok else "CHANGED"))
        json.dump(rows, open(os.path.join(a.out, "v3_results.json"), "w",
                             encoding="utf-8"), ensure_ascii=False, indent=2)
        print("\n%d/%d vectors reproduced exactly" % (len(vecs) - nfail, len(vecs)))
        return 0 if nfail == 0 else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
