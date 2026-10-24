# -*- coding: utf-8 -*-
r"""Build real calibration sets and fp32 references for every GLC subgraph.

For each of N Kodak crops this runs the *exact* split that the ONNX subgraphs
implement (same modules c1_export_subgraphs.py exports) and dumps:

  calib/<sub>/<i>.ftmp      input(s) in icraft's NHWC ftmp layout, one file
                            per input (multi-input nets use ; in the list)
  calib/<sub>/list.txt      forward_list entries
  refs/<sub>_<out>_<i>.npy  fp32 reference for every subgraph output

Layout convention (verified against icraft's parsed Input values, which are
always @layout(NHWC)):
  torch NCHW (1,C,H,W)  ->  np.transpose(0,2,3,1)  ->  (1,H,W,C) raw float32

Subgraphs and their tensors
  s1_encoder_ga_hyper : x(1,3,256,256)            -> y(1,256,16,16), z(1,256,4,4)
  s2_hyperdec_fusion  : z_hat(1,256,4,4)          -> common_params(1,768,16,16)
  s3_phase{1,2,3}     : y_hat_so_far, common_red  -> scales, means (1,256,16,16)
  s4_gs_generator     : y_hat(1,256,16,16)        -> x_hat(1,3,256,256)

Usage:
  <envs\glc\python.exe> c1_make_calib_refs.py --repo <GLC repo> --model <ckpt>
      --out E:\fudanwei\工作区\calibref [--n 8] [--size 256] [--q 0]
"""
import argparse
import importlib.util
import os
import sys

import numpy as np
import torch
from PIL import Image


def load_export_module(tools_dir):
    p = os.path.join(tools_dir, "c1_export_subgraphs.py")
    spec = importlib.util.spec_from_file_location("c1exp", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def nhwc(t):
    """torch NCHW -> contiguous NHWC float32 numpy array."""
    return np.ascontiguousarray(t.detach().cpu().numpy().transpose(0, 2, 3, 1))


def dump(path, arr):
    arr.astype(np.float32).tofile(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tools", default=r"E:\fudanwei\工作区\tools")
    ap.add_argument("--png_dir", default=r"E:\fudanwei\工作区\testset\kodak",
                    help="one directory, or several separated by ',' (samples are "
                         "taken round-robin across all of them)")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--q", type=int, default=0)
    ap.add_argument("--simple_attn", action="store_true", default=True)
    a = ap.parse_args()

    repo = os.path.abspath(a.repo)
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "src", "utils"))
    from src.models.image_model import GLC_Image
    from src.utils.test_utils import get_state_dict

    exp = load_export_module(a.tools)
    model = GLC_Image(inplace=True)
    model.load_state_dict(get_state_dict(a.model), strict=True)
    model.eval()
    if a.simple_attn:
        exp.patch_attention_to_full(repo, model)
    s1, s2, s3s, s4 = exp.build_modules(model, a.q)

    subs = ["s1_encoder_ga_hyper", "s2_hyperdec_fusion",
            "s3_phase1", "s3_phase2", "s3_phase3", "s4_gs_generator"]
    for s in subs:
        os.makedirs(os.path.join(a.out, "calib", s), exist_ok=True)
        os.makedirs(os.path.join(a.out, "refs"), exist_ok=True)

    pngs = []
    for d in [x.strip() for x in a.png_dir.split(",") if x.strip()]:
        fs = sorted(f for f in os.listdir(d)
                    if f.lower().endswith((".png", ".jpg", ".jpeg")))
        for f in fs:
            pngs.append(os.path.join(d, f))
    print("calibration pool: %d real images from %s"
          % (len(pngs), a.png_dir))
    S, L, Z = a.size, a.size // 16, a.size // 64
    lists = {s: [] for s in subs}

    for i in range(a.n):
        im = Image.open(pngs[i % len(pngs)]).convert("RGB")
        w, h = im.size
        if w < S or h < S:
            raise SystemExit("image %s is %dx%d, smaller than the %d crop"
                             % (pngs[i % len(pngs)], w, h, S))
        x0 = (i * 37) % max(1, w - S)
        y0 = (i * 53) % max(1, h - S)
        im = im.crop((x0, y0, x0 + S, y0 + S))
        px = np.asarray(im, dtype=np.float32) / 127.5 - 1.0          # (S,S,3)
        x = torch.from_numpy(px.transpose(2, 0, 1)).unsqueeze(0).contiguous()

        with torch.no_grad():
            y, z = s1(x)
            idx = model.z_vq.get_indices(z)
            z_hat = model.z_vq.get_quan_feat(
                idx, (z.shape[0], z.shape[2], z.shape[3], z.shape[1]))
            params = s2(z_hat)
            q_enc_, q_dec_, scales0, means0 = model.separate_prior(params)
            common_red = model.y_spatial_prior_reduction(params)

            # Replicate split_forward() exactly so that every subgraph input we
            # write as calibration data is the *same tensor* its reference
            # output was computed from.
            masks = model.get_mask_four_parts(*y.shape, y.dtype, y.device)
            y_scaled = y * q_enc_
            y_hat_so_far = torch.zeros_like(y)
            s3_io = {}
            for stage, mask in enumerate(masks):
                if stage == 0:
                    s_, m_ = scales0, means0
                else:
                    inp = (y_hat_so_far, common_red)
                    s_, m_ = s3s[stage - 1](*inp)
                    s3_io[stage] = (inp, (s_, m_))
                _, _, y_hat_k, _ = model.process_with_mask(y_scaled, s_, m_, mask)
                y_hat_so_far = y_hat_so_far + y_hat_k
            y_hat = y_hat_so_far * q_dec_
            x_hat = s4(y_hat)
            phase_in = {k: v[0] for k, v in s3_io.items()}      # partial y_hat
            phase_out = {k: v[1] for k, v in s3_io.items()}

        # ---- write calibration inputs (NHWC ftmp) ----
        dump(os.path.join(a.out, "calib", "s1_encoder_ga_hyper", "%02d.ftmp" % i), px)
        lists["s1_encoder_ga_hyper"].append("%02d.ftmp" % i)

        dump(os.path.join(a.out, "calib", "s2_hyperdec_fusion", "%02d.ftmp" % i), nhwc(z_hat))
        lists["s2_hyperdec_fusion"].append("%02d.ftmp" % i)

        for k in (1, 2, 3):
            fn = "%02d.ftmp" % i
            pyr, cred = phase_in[k]
            dump(os.path.join(a.out, "calib", "s3_phase%d" % k, fn), nhwc(pyr))
            dump(os.path.join(a.out, "calib", "s3_phase%d" % k, "%02d_b.ftmp" % i), nhwc(cred))
            lists["s3_phase%d" % k].append("%s;%02d_b.ftmp" % (fn, i))

        dump(os.path.join(a.out, "calib", "s4_gs_generator", "%02d.ftmp" % i), nhwc(y_hat))
        lists["s4_gs_generator"].append("%02d.ftmp" % i)

        # ---- write fp32 references (NCHW npy, for hb_score-style comparison) ----
        np.save(os.path.join(a.out, "refs", "s1_y_%02d.npy" % i), y.numpy())
        np.save(os.path.join(a.out, "refs", "s1_z_%02d.npy" % i), z.numpy())
        np.save(os.path.join(a.out, "refs", "s2_params_%02d.npy" % i), params.numpy())
        for k in (1, 2, 3):
            s_, m_ = phase_out[k]
            np.save(os.path.join(a.out, "refs", "s3p%d_scales_%02d.npy" % (k, i)), s_.numpy())
            np.save(os.path.join(a.out, "refs", "s3p%d_means_%02d.npy" % (k, i)), m_.numpy())
        np.save(os.path.join(a.out, "refs", "s4_xhat_%02d.npy" % i), x_hat.numpy())

        print("  sample %02d  %-28s  y%s z%s params%s x_hat%s"
              % (i, os.path.relpath(pngs[i % len(pngs)]), tuple(y.shape),
                 tuple(z.shape), tuple(params.shape), tuple(x_hat.shape)))

    for s in subs:
        with open(os.path.join(a.out, "calib", s, "list.txt"), "w") as f:
            f.write("\n".join(lists[s]) + "\n")
    print("\n校准集与参考量已写入 " + os.path.abspath(a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
