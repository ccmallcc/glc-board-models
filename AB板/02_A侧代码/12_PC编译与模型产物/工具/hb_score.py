# -*- coding: utf-8 -*-
r"""Score Icraft HostBackend ftmp dumps against the PyTorch fp32 reference.

The dumped ftmp files are headerless raw little-endian fp32 in NHWC layout and
are named after the runtime v_id.  Rather than hard-coding v_ids (they shift
between graphs) the outputs are identified by element count:
  y (encoder latent)     1x16x16x256 = 65536
  z (hyper latent)       1x4x4x256   = 4096

Usage:
  python hb_score.py --dump <ftmpSFB dir> --ref <dir with ref_s1_y/z.npy>
                     --label int8 [--also-scan]
"""
import argparse
import os
import sys

import numpy as np

# (element count, NHWC shape as icraft lays it out, human description)
REF = {"ref_s1_y.npy": (65536, (1, 16, 16, 256), "y  (latent 16x16x256)"),
       "ref_s1_z.npy": (4096, (1, 4, 4, 256), "z  (hyper 4x4x256)")}


def load(path, shape):
    a = np.fromfile(path, dtype=np.float32)
    return a.reshape(shape)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", required=True)
    ap.add_argument("--ref", required=True)
    ap.add_argument("--label", default="")
    ap.add_argument("--also-scan", action="store_true",
                    help="also report NaN/Inf census of every dump")
    a = ap.parse_args()

    files = {}
    for root, _d, fs in os.walk(a.dump):
        for f in fs:
            if f.endswith(".ftmp"):
                p = os.path.join(root, f)
                files[f[:-5]] = p

    if a.also_scan:
        print("  --- dump census ---")
        for vid in sorted(files, key=lambda x: int(x) if x.isdigit() else 0):
            arr = np.fromfile(files[vid], dtype=np.float32)
            nan = int(np.isnan(arr).sum())
            inf = int(np.isinf(arr).sum())
            fin = arr[np.isfinite(arr)]
            print("    v_id=%-6s n=%-8d nan=%-7d inf=%-6d max=%.5g mean_abs=%.5g"
                  % (vid, arr.size, nan, inf,
                     float(np.abs(fin).max()) if fin.size else float("nan"),
                     float(np.abs(fin).mean()) if fin.size else float("nan")))

    print("  === %s vs PyTorch fp32 reference ===" % (a.label or a.dump))
    allok = True
    for refname, (n, icshape, desc) in REF.items():
        rp = os.path.join(a.ref, refname)
        if not os.path.exists(rp):
            print("    [skip] missing %s" % refname)
            continue
        cand = [v for v, p in files.items()
                if os.path.getsize(p) // 4 == n]
        if not cand:
            print("    [skip] no dump with %d elements for %s" % (n, desc))
            allok = False
            continue
        ref = np.load(rp)
        for vid in sorted(cand):
            ic = load(files[vid], icshape)              # NHWC
            ic = np.transpose(ic, (0, 3, 1, 2))         # -> NCHW
            if ic.shape != ref.shape:
                print("    [skip] v_id %s shape %s vs ref %s" % (vid, ic.shape, ref.shape))
                continue
            d = np.abs(ic - ref)
            cos = float((ic.ravel() @ ref.ravel()) /
                        (np.linalg.norm(ic) * np.linalg.norm(ref) + 1e-12))
            rel = float(d.max() / max(1e-12, np.abs(ref).max()))
            print("    %-24s v_id=%-6s" % (desc, vid))
            print("        ref range [%.4f, %.4f]  max|Δ|=%.4e  mean|Δ|=%.4e  rel=%.3e"
                  % (ref.min(), ref.max(), d.max(), d.mean(), rel))
            print("        cosine = %.8f   PSNR = %.2f dB"
                  % (cos, 10 * np.log10(1.0 / max(1e-12, float((d ** 2).mean())))))
            if cos < 0.999:
                allok = False
    print("  VERDICT: %s" % ("OK (cosine >= 0.999 on all outputs)" if allok else "REVIEW"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
