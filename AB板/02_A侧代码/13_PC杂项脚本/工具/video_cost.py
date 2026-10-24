# -*- coding: utf-8 -*-
r"""Measure GLC-Video's cost profile: parameters, per-frame time, peak memory.

Answers "how big a video can the board handle, at what frame rate?" without
needing the 502 MB checkpoint -- the architecture (and therefore the cost) is
identical with random weights.

The video codec is I/P: every `intra_period`-th frame is coded by GLC_Image
(the model we already deployed), the rest by GLC_Video using a decoded picture
buffer (dpb).  So the per-frame average is

    cost_avg = (cost_I + (GOP-1) * cost_P) / GOP

Usage (in envs\glc):
  python video_cost.py --repo <GLC> [--sizes 256,512,720,1080] [--iters 3]
"""
import argparse
import os
import sys
import time

import torch


def human(n):
    return "%.1f M" % (n / 1e6)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--sizes", default="256,512,720,1080",
                    help="frame heights; width = height*16/9 rounded to /16")
    ap.add_argument("--iters", type=int, default=3)
    ap.add_argument("--gop", type=int, default=8)
    ap.add_argument("--cpu", action="store_true")
    a = ap.parse_args()

    repo = os.path.abspath(a.repo)
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "src", "utils"))
    from src.models.image_model import GLC_Image
    from src.models.video_model import GLC_Video

    dev = torch.device("cpu" if a.cpu else "cuda")
    if not a.cpu and not torch.cuda.is_available():
        dev = torch.device("cpu")
    print("device: %s%s" % (dev, (" (" + torch.cuda.get_device_name(0) + ")")
                            if dev.type == "cuda" else ""))

    def count(m):
        seen, tot = set(), 0
        for p in m.parameters():
            if id(p) not in seen:
                seen.add(id(p))
                tot += p.numel()
        return tot

    print("\n=== 参数量 ===")
    vi = GLC_Image(inplace=True)
    vp = GLC_Video(inplace=True)
    n_i, n_p = count(vi), count(vp)
    print("  GLC_Image (I 帧)      : %s" % human(n_i))
    print("  GLC_Video (P 帧)      : %s" % human(n_p))
    vq_i = count(vi.vqgan)
    vq_p = count(vp.vqgan)
    print("  └ 其中 VQGAN 共用     : %s / %s" % (human(vq_i), human(vq_p)))
    # non-VQGAN parts, i.e. what the P-frame path adds on top of the VQGAN
    print("  P 帧独有（去掉 VQGAN）: %s" % human(n_p - vq_p))
    print("  I 帧独有（去掉 VQGAN）: %s" % human(n_i - vq_i))

    vi.to(dev).eval()
    vp.to(dev).eval()

    def bench(fn, iters, warmup=1):
        for _ in range(warmup):
            fn()
        if dev.type == "cuda":
            torch.cuda.synchronize()
            torch.cuda.reset_peak_memory_stats()
        t0 = time.time()
        for _ in range(iters):
            out = fn()
        if dev.type == "cuda":
            torch.cuda.synchronize()
        dt = (time.time() - t0) / iters
        mem = torch.cuda.max_memory_allocated() / 1e9 if dev.type == "cuda" else 0.0
        return dt, mem, out

    class ZeroGen(torch.nn.Module):
        """Stand-in for vqgan.generator.

        The P-frame encoder writes dpb['ref_frame'] = self.vqgan.generator(...)
        but NOTHING in the encode path ever reads ref_frame -- only
        ref_latent (context generation) and ref_y (prior params) are consumed
        (video_model.py lines 269-272, 279-280 vs the write at line 346).
        So a bitstream-only encoder can skip the generator entirely; this
        module measures how much that saves.
        """
        def __init__(self, shape):
            super().__init__()
            self.shape = shape

        def forward(self, x):
            return torch.zeros(self.shape, device=x.device, dtype=x.dtype)

    print("\n=== 单帧实测（RTX 4060 Laptop 8GB，fp32）===")
    print("%-24s %9s %9s %9s %9s %8s" %
          ("分辨率", "I帧(s)", "P帧(s)", "P帧-无生成器", "GOP=%d均值" % a.gop, "显存GB"))
    rows = []
    for h in [int(x) for x in a.sizes.split(",")]:
        w = (int(h * 16 / 9) + 15) // 16 * 16
        # pad to multiple of 64 like test_video.py does
        hp, wp = (h + 63) // 64 * 64, (w + 63) // 64 * 64
        try:
            x = torch.randn(1, 3, hp, wp, device=dev)
            L = hp // 16
            Wl = wp // 16
            lat = torch.randn(1, 256, L, Wl, device=dev)
            with torch.no_grad():
                t_i, mem_i, _ = bench(lambda: vi.test(x, 0), a.iters)
                dpb = {"ref_frame": torch.randn(1, 3, hp, wp, device=dev),
                       "ref_latent": lat, "latent_ori": lat.clone(),
                       "ref_y": torch.randn(1, 256, L, Wl, device=dev)}
                t_p, mem_p, _ = bench(lambda: vp.test(x, dpb, 0, 0), a.iters)

                saved = vp.vqgan.generator
                vp.vqgan.generator = ZeroGen((1, 3, hp, wp))
                t_pe, mem_pe, _ = bench(lambda: vp.test(x, dpb, 0, 0), a.iters)
                vp.vqgan.generator = saved

            avg = (t_i + (a.gop - 1) * t_pe) / a.gop
            rows.append((h, w, hp, wp, t_i, t_p, t_pe, max(mem_i, mem_p, mem_pe), avg))
            print("%-24s %9.3f %9.3f %12.3f %9.3f %8.2f"
                  % ("%dx%d(pad %dx%d)" % (w, h, wp, hp), t_i, t_p, t_pe,
                     max(mem_i, mem_p, mem_pe), avg))
        except RuntimeError as e:
            print("%-24s  OOM/失败: %s" % ("%dx%d" % (w, h), str(e)[:60]))
            if dev.type == "cuda":
                torch.cuda.empty_cache()

    if rows:
        print("\n=== 汇总（RTX 4060，fp32；I帧为完整 GLC_Image，P帧为去掉生成器后的编码端）===")
        print("%-24s %9s %9s %12s" % ("分辨率", "I帧(s)", "P帧-无生成器(s)", "P/I 比"))
        for r in rows:
            h, w, hp, wp, t_i, t_p, t_pe, mem, avg = r
            i_enc = t_i * 0.48          # 编码端约占 GLC_Image 全前向的 48%
            print("%-24s %9.3f %9.3f %12.2f"
                  % ("%dx%d" % (w, h), i_enc, t_pe, t_pe / i_enc if i_enc else 0))
        print("\n注：I 帧的『编码端』按实测比例 0.48（= `split_timing.py` 的 30.8/64.0 @256²）折算，"
              "不含 VQGAN 生成器。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
