# -*- coding: utf-8 -*-
r"""PS-side reference implementation of the GLC bookkeeping (plan item C2/B4/B5).

Two pieces of the "PS 侧状态机" are pure host logic with no NPU involvement, so
they can be fully specified and validated now, without a board:

  B4  VQ-E argmin + VQ-D codebook lookup   (16384 x 256 nearest neighbour)
  B5  four-phase bookkeeping               (mask multiply / round / y_hat accumulate)
      + C2 four-phase state machine skeleton (encoder & decoder sides)

Everything here is plain NumPy, written the way the C++/PS port would be
(flat buffers, explicit loops over phases, int32 accumulation for the VQ
distance), and then checked **bit-exactly** against the PyTorch model:

  * get_indices  / get_quan_feat   vs the NumPy argmin + lookup
  * forward_four_part_prior        vs the NumPy four-phase loop

Usage (in envs\glc):
  python ps_ref_state_machine.py --repo <GLC> --model <ckpt>
       [--size 256] [--q 0] [--png <kodak dir>] [--bench]
"""
import argparse
import math
import os
import sys
import time

import numpy as np
import torch
from PIL import Image


# --------------------------------------------------------------------------
# B4: VQ-E argmin + VQ-D lookup, written as the PS would implement it
# --------------------------------------------------------------------------
def vq_encode_numpy(z_nchw, codebook):
    """z (1,C,H,W) -> indices (H*W,) int32.

    Mirrors GLC's get_indices(): permute to (B,H,W,C), flatten, then
    argmin over ||z - e||^2 = ||z||^2 + ||e||^2 - 2 z.e^T.
    Written with an explicit int32 accumulation over the embedding dimension
    and a streaming argmin, because that is what the PS port does (the NPU
    cannot be trusted to do a 16384-way argmin at full precision).
    """
    _, C, H, W = z_nchw.shape
    zf = np.ascontiguousarray(z_nchw[0].transpose(1, 2, 0)).reshape(H * W, C).astype(np.float32)
    N, K = zf.shape[0], codebook.shape[0]
    idx = np.empty(N, dtype=np.int32)
    zbuf = np.empty(K, dtype=np.float32)
    for n in range(N):
        row = zf[n]
        # |z|^2 + |e|^2 - 2 z.e  via float32 accumulation, same order as torch
        best = np.float32(0.0)
        besti = 0
        zsq = np.float32(np.dot(row, row))
        for k in range(K):
            e = codebook[k]
            d = zsq + np.float32(np.dot(e, e)) - np.float32(2.0) * np.float32(np.dot(row, e))
            if k == 0 or d < best:
                best = d
                besti = k
        idx[n] = besti
    return idx


def vq_decode_numpy(indices, codebook, H, W):
    """indices (H*W,) -> z_hat (1,C,H,W) float32."""
    C = codebook.shape[1]
    zq = codebook[indices.astype(np.int64)]                 # (H*W, C)
    zq = zq.reshape(H, W, C).transpose(2, 0, 1)[None]       # (1,C,H,W)
    return np.ascontiguousarray(zq).astype(np.float32)


# --------------------------------------------------------------------------
# B5 / C2: four-phase bookkeeping
# --------------------------------------------------------------------------
def masks_numpy(C, H, W):
    """Same masks as CommonModel.get_mask_four_parts.

    Not a plain checkerboard product: each of the four masks interleaves
    *channel groups* with *spatial parity*.  Per period-2 micro mask
        m0=[[1,0],[0,0]]  m1=[[0,1],[0,0]]  m2=[[0,0],[1,0]]  m3=[[0,0],[0,1]]
    the channel dimension is split into 4 groups and each phase permutes the
    four micro masks across the groups:
        mask_0 = cat(g0*m0, g1*m1, g2*m2, g3*m3)
        mask_1 = cat(g0*m3, g1*m2, g2*m1, g3*m0)
        mask_2 = cat(g0*m2, g1*m3, g2*m0, g3*m1)
        mask_3 = cat(g0*m1, g1*m0, g2*m3, g3*m2)
    Every mask therefore selects exactly 1/4 of all elements.
    """
    assert C % 4 == 0
    micros = [np.array(((1, 0), (0, 0)), dtype=np.float32),
              np.array(((0, 1), (0, 0)), dtype=np.float32),
              np.array(((0, 0), (1, 0)), dtype=np.float32),
              np.array(((0, 0), (0, 1)), dtype=np.float32)]
    tiles = []
    for mu in micros:
        t = np.tile(mu, ((H + 1) // 2, (W + 1) // 2))[:H, :W]
        tiles.append(t.reshape(1, 1, H, W))
    perm = {0: (0, 1, 2, 3), 1: (3, 2, 1, 0), 2: (2, 3, 0, 1), 3: (1, 0, 3, 2)}
    g = C // 4
    out = []
    for phase in range(4):
        p = perm[phase]
        out.append(np.concatenate([tiles[p[i]] * np.ones((1, g, H, W), np.float32)
                                   for i in range(4)], axis=1))
    return out


def process_with_mask_numpy(y, scales, means, mask):
    """Mirrors CommonModel.process_with_mask exactly."""
    scales_hat = scales * mask
    means_hat = means * mask
    y_res = (y - means_hat) * mask
    y_q = np.round(y_res)
    y_hat = y_q + means_hat
    return y_res, y_q, y_hat, scales_hat


def four_phase_decode_numpy(y_scaled, masks, scales_list, means_list, q_dec):
    """Decoder-side state machine: 4 phases, phase k uses (scales_k, means_k).

    Returns (y_hat, bits) where bits is the analytic entropy of the residuals
    under N(0, scales_hat) -- same formula as CommonModel.get_y_gaussian_bits.
    """
    y_hat_so_far = np.zeros_like(y_scaled)
    total_bits = 0.0
    per_phase_bits = []
    for k, mask in enumerate(masks):
        _res, y_q, y_hat_k, sc_hat = process_with_mask_numpy(
            y_scaled, scales_list[k], means_list[k], mask)
        sig = np.clip(sc_hat, 1e-5, 1e10)
        # P(y-0.5 < X < y+0.5) with X ~ N(0, sigma), via erf
        cdf_p = 0.5 * (1.0 + _erf((y_q + 0.5) / (sig * math.sqrt(2.0))))
        cdf_m = 0.5 * (1.0 + _erf((y_q - 0.5) / (sig * math.sqrt(2.0))))
        probs = np.maximum(cdf_p - cdf_m, 1e-7)
        b = float(np.clip(-np.log(probs + 1e-5) / math.log(2.0), 0, None).sum())
        per_phase_bits.append(b)
        total_bits += b
        y_hat_so_far = y_hat_so_far + y_hat_k
    return y_hat_so_far * q_dec, total_bits, per_phase_bits


def _erf(x):
    """erf via numpy (scipy-free) -- math.erf vectorised."""
    v = np.vectorize(math.erf, otypes=[np.float64])
    return v(x)


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--png_dir", default=r"E:\fudanwei\工作区\testset\kodak")
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--q", type=int, default=0)
    ap.add_argument("--bench", action="store_true",
                    help="also time the NumPy VQ and extrapolate to a real frame")
    a = ap.parse_args()

    repo = os.path.abspath(a.repo)
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "src", "utils"))
    from src.models.image_model import GLC_Image
    from src.utils.test_utils import get_state_dict

    model = GLC_Image(inplace=True)
    model.load_state_dict(get_state_dict(a.model), strict=True)
    model.eval()

    cb = model.z_vq.embedding.weight.detach().numpy().astype(np.float32)
    print("codebook: %s   emb_dim=%d  codebook_size=%d  = %.2f MB fp32 / %.2f MB int8"
          % (cb.shape, cb.shape[1], cb.shape[0], cb.nbytes / 1e6, cb.size / 1e6))

    pngs = sorted(f for f in os.listdir(a.png_dir) if f.lower().endswith(".png"))
    S = a.size
    im = Image.open(os.path.join(a.png_dir, pngs[0])).convert("RGB").crop((0, 0, S, S))
    px = np.asarray(im, dtype=np.float32) / 127.5 - 1.0
    x = torch.from_numpy(px.transpose(2, 0, 1)).unsqueeze(0).contiguous()

    ok_all = True
    with torch.no_grad():
        # ---------------- B4: VQ ----------------
        curr_q_enc = model.q_enc[a.q:a.q + 1]
        curr_q_dec = model.q_dec[a.q:a.q + 1]
        y = model.enc(model.vqgan.encoder(x), curr_q_enc)
        z = model.hyper_enc(y)
        H, W = z.shape[2], z.shape[3]

        idx_t = model.z_vq.get_indices(z)
        zq_t = model.z_vq.get_quan_feat(idx_t, (1, z.shape[2], z.shape[3], z.shape[1]))

        t0 = time.time()
        idx_np = vq_encode_numpy(z.numpy(), cb)
        t_vq_enc = time.time() - t0
        zq_np = vq_decode_numpy(idx_np, cb, H, W)
        t_vq_dec = time.time() - t0 - t_vq_enc

        idx_ref = idx_t.squeeze(1).numpy().astype(np.int32)
        same = int((idx_np == idx_ref).sum())
        print("\n=== B4 VQ-E argmin ===")
        print("  索引逐个一致: %d / %d %s" % (same, idx_ref.size,
                                            "✅" if same == idx_ref.size else "❌"))
        print("  VQ-D 查表最大误差 = %.3e %s"
              % (np.abs(zq_np - zq_t.numpy()).max(),
                 "✅" if np.abs(zq_np - zq_t.numpy()).max() == 0 else "⚠️"))
        ok_all &= (same == idx_ref.size) and np.abs(zq_np - zq_t.numpy()).max() == 0

        # ---------------- B5 / C2: four phases ----------------
        params = model.y_prior_fusion(model.hyper_dec(zq_t))
        q_enc_, q_dec_, scales0, means0 = model.separate_prior(params)
        common = model.y_spatial_prior_reduction(params)
        masks = model.get_mask_four_parts(*y.shape, y.dtype, y.device)
        y_scaled = y * q_enc_
        masks_np = masks_numpy(y.shape[1], y.shape[2], y.shape[3])

        scales_t, means_t = [], []
        for k in range(4):
            if k == 0:
                s_, m_ = scales0, means0
            else:
                s_, m_ = model.y_spatial_prior(
                    getattr(model, "y_spatial_prior_adaptor_%d" % k)(
                        torch.cat((yh_t, common), 1))).chunk(2, 1)
            scales_t.append(s_)
            means_t.append(m_)
            _, _, yh_k, _ = model.process_with_mask(y_scaled, s_, m_, masks[k])
            yh_t = yh_k if k == 0 else yh_t + yh_k

        ref = model.test(x, a.q)

    yh_np, bits_np, per_phase = four_phase_decode_numpy(
        y_scaled.numpy(), masks_np,
        [t.numpy() for t in scales_t], [t.numpy() for t in means_t], q_dec_.numpy())

    # NOTE: model.test()["ref_latent"] is *dec(y_hat)*, not the four-phase y_hat.
    # The correct comparison target is y_hat_so_far * q_dec computed above.
    y_hat_t = (yh_t * q_dec_).numpy()
    d = np.abs(yh_np - y_hat_t).max()
    print("\n=== B5/C2 四相位记账（解码侧）===")
    print("  相位掩码元素数: %s（四等分，共 %d）"
          % ([int(m.sum()) for m in masks_np], int(sum(m.sum() for m in masks_np))))
    print("  y_hat 最大绝对误差 = %.3e %s" % (d, "✅ bit-exact" if d == 0 else "⚠️ 有差异"))
    ok_all &= (d == 0)
    print("  逐相位解析码率(bits): %s" % ["%.1f" % b for b in per_phase])
    print("  y 总码率 = %.1f bits = %.5f bpp（%.0f×%.0f）"
          % (bits_np, bits_np / (S * S), S, S))
    print("  参考实现 model.test() 的 bit_y = %.1f bits" % ref["bit_y"])

    if a.bench:
        N = H * W
        print("\n=== 性能外推（NumPy 单线程，纯 Python 内层循环）===")
        print("  z 规模 %d×%d×%d = %d 个位置；VQ-E 用时 %.3f s" % (H, W, cb.shape[1], N, t_vq_enc))
        per_pos = t_vq_enc / max(1, N)
        print("  单点 %.3f ms（纯 Python 循环，最坏情况基准）" % (per_pos * 1e3))
        print("  → C++ 用 BLAS/NEON 内积 + 4 核并行，预计快 100~1000×：%.2f~%.2f ms/次"
              % (per_pos * N * 1e3 / 1000, per_pos * N * 1e3 / 100))
        print("  → 256×256 输入的 z 只有 %d 个位置，VQ 在 PS 上不是瓶颈" % N)
        print("  VQ-D 查表 %.4f s（纯内存拷贝，可忽略）" % t_vq_dec)

    print("\n%s" % ("全部 ✅ bit-exact" if ok_all else "存在差异，见上"))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
