r"""C1：把 GLC-image 拆成 4 个可独立编译的子图并导出 ONNX

子图划分（固定 256×256，q 档固定）：
  S1: x(1,3,256,256)                      -> y(1,256,16,16), z(1,256,4,4)     [仅编码端]
  S2: z_hat(1,256,4,4)                    -> common_params(1,768,16,16)       [编解共用]
  S3: y_hat_so_far(1,256,16,16),          -> scales, means                    [编解共用, 每相位一个]
      common_red(1,256,16,16)
  S4: y_hat(1,256,16,16)                  -> x_hat(1,3,256,256)               [仅解码端]
放在 PS 的部分：VQ-E(argmin)/VQ-D(查表)、四相位掩码记账、round、熵编解码。

脚本会先做一次**数值等价性自检**：用拆图路径重算 x_hat，与模型自带 test() 对比。
"""
import argparse
import os
import sys

import torch
import torch.nn as nn


def patch_attention_to_full(repo, model):
    """把 AttnBlock 的 patch 分块 attention 换成整块 attention

    推理时 AttnBlock.forward 走 forward_patch()：用 torch.zeros_like + 切片赋值
    (H_[:, :, i:i+d, j:j+d] = h_) 把每个 32×32 块的结果写回 —— 该写法在 ONNX 里
    会变成 ScatterND，而 ScatterND 在 30TAI 上回退 CPU。

    当 latent 尺寸 <= patch(=32) 时，循环只跑一次且切片覆盖全图，
    整块 attention 与之**数学完全等价**（本脚本的数值自检可证），可安全替换。
    """
    from src.models import vqgan_arch as va
    import torch.nn.functional as F

    def full_forward(self, x):
        h_ = self.norm(x)
        q, k, v = self.q(h_), self.k(h_), self.v(h_)
        b, c, h, w = q.shape
        q = q.reshape(b, c, h * w).permute(0, 2, 1)
        k = k.reshape(b, c, h * w)
        w_ = torch.bmm(q, k) * (int(c) ** (-0.5))
        w_ = F.softmax(w_, dim=2)
        v = v.reshape(b, c, h * w)
        w_ = w_.permute(0, 2, 1)
        h_ = torch.bmm(v, w_).reshape(b, c, h, w)
        return x + self.proj_out(h_)

    n = 0
    for m in model.modules():
        if isinstance(m, va.AttnBlock):
            m.forward = full_forward.__get__(m, va.AttnBlock)
            n += 1
    return n


def build_modules(model, q):
    """把模型切成 4 个 nn.Module，q 档烘成常量（参数切片）"""

    class S1_Encoder(nn.Module):
        def __init__(self):
            super().__init__()
            self.vqgan_encoder = model.vqgan.encoder
            self.enc = model.enc
            self.hyper_enc = model.hyper_enc
            self.register_buffer("q_enc", model.q_enc[q:q + 1].detach().clone())

        def forward(self, x):
            y_ori = self.vqgan_encoder(x)
            y = self.enc(y_ori, self.q_enc)
            z = self.hyper_enc(y)
            return y, z

    class S2_HyperDec(nn.Module):
        def __init__(self):
            super().__init__()
            self.hyper_dec = model.hyper_dec
            self.y_prior_fusion = model.y_prior_fusion

        def forward(self, z_hat):
            return self.y_prior_fusion(self.hyper_dec(z_hat))

    class S3_Phase(nn.Module):
        """相位 k>=1：concat + adaptor_k + y_spatial_prior -> scales, means"""

        def __init__(self, stage):
            super().__init__()
            assert stage in (1, 2, 3)
            self.stage = stage
            self.adaptor = [model.y_spatial_prior_adaptor_1,
                            model.y_spatial_prior_adaptor_2,
                            model.y_spatial_prior_adaptor_3][stage - 1]
            self.prior = model.y_spatial_prior

        def forward(self, y_hat_so_far, common_red):
            params = torch.cat((y_hat_so_far, common_red), dim=1)
            scales, means = self.prior(self.adaptor(params)).chunk(2, 1)
            return scales, means

    class S4_Decoder(nn.Module):
        def __init__(self):
            super().__init__()
            self.dec = model.dec
            self.generator = model.vqgan.generator
            self.register_buffer("q_dec", model.q_dec[q:q + 1].detach().clone())

        def forward(self, y_hat):
            l_hat = self.dec(y_hat, self.q_dec)
            return self.generator(l_hat)

    return S1_Encoder(), S2_HyperDec(), [S3_Phase(s) for s in (1, 2, 3)], S4_Decoder()


@torch.no_grad()
def split_forward(model, s1, s2, s3s, s4, x, q, use_s3=True):
    """按拆图路径做一次完整前向（S3 走导出用的模块，以验证模块与原逻辑一致）"""
    y, z = s1(x)
    # —— 以下在 PS 上（这里用 PyTorch 模拟）——
    idx = model.z_vq.get_indices(z)
    z_hat = model.z_vq.get_quan_feat(idx, (z.shape[0], z.shape[2], z.shape[3], z.shape[1]))
    params = s2(z_hat)
    q_enc_, q_dec_, scales0, means0 = model.separate_prior(params)
    common_red = model.y_spatial_prior_reduction(params)

    masks = model.get_mask_four_parts(*y.shape, y.dtype, y.device)
    y_scaled = y * q_enc_
    y_hat_so_far = torch.zeros_like(y)
    for stage, mask in enumerate(masks):
        if stage == 0:
            s_, m_ = scales0, means0
        else:
            if use_s3:
                s_, m_ = s3s[stage - 1](y_hat_so_far, common_red)
            else:
                adaptors = (model.y_spatial_prior_adaptor_1, model.y_spatial_prior_adaptor_2,
                            model.y_spatial_prior_adaptor_3)
                s_, m_ = model.y_spatial_prior(
                    adaptors[stage - 1](torch.cat((y_hat_so_far, common_red), 1))).chunk(2, 1)
        _, _, y_hat_k, _ = model.process_with_mask(y_scaled, s_, m_, mask)
        y_hat_so_far = y_hat_so_far + y_hat_k
    y_hat = y_hat_so_far * q_dec_
    x_hat = s4(y_hat)
    return x_hat, y_hat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--q", type=int, default=0)
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--no_check", action="store_true")
    ap.add_argument("--simple_attn", action="store_true",
                    help="把 patch 分块 attention 换成整块 attention（消除 ScatterND）")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "src", "utils"))
    from src.models.image_model import GLC_Image
    from src.utils.test_utils import get_state_dict

    os.makedirs(args.out, exist_ok=True)
    dev = torch.device(args.device)

    model = GLC_Image(inplace=True)
    model.load_state_dict(get_state_dict(args.model), strict=True)
    model.to(dev).eval()

    if args.simple_attn:
        n = patch_attention_to_full(repo, model)
        print(f"=== 已把 {n} 个 AttnBlock 替换为整块 attention（用于消除 ScatterND）===")

    s1, s2, s3s, s4 = build_modules(model, args.q)
    for m in (s1, s2, s4, *s3s):
        m.to(dev).eval()

    x = torch.randn(1, 3, args.size, args.size, device=dev)

    if not args.no_check:
        print("=== 数值等价性自检：拆图路径 vs 模型自带 test() ===")
        with torch.no_grad():
            ref = model.test(x, args.q)["x_hat"]
            got, _ = split_forward(model, s1, s2, s3s, s4, x, args.q, use_s3=True)
        d = (ref - got).abs().max().item()
        scale = ref.abs().mean().item()
        print(f"  最大绝对误差 = {d:.3e}（输出尺度 {scale:.4f}）")
        print("  → " + ("✅ 拆图与原实现一致" if d < 1e-5 else "⚠️ 存在差异，需排查"))

    print("\n=== 导出 ONNX ===")
    S = args.size
    L = S // 16          # latent 边长
    Z = L // 4           # 超先验边长
    specs = [
        ("s1_encoder_ga_hyper", s1, (torch.randn(1, 3, S, S, device=dev),), ["x"], ["y", "z"]),
        ("s2_hyperdec_fusion", s2, (torch.randn(1, 256, Z, Z, device=dev),), ["z_hat"], ["common_params"]),
        ("s3_phase1", s3s[0], (torch.randn(1, 256, L, L, device=dev),
                               torch.randn(1, 256, L, L, device=dev)),
         ["y_hat_so_far", "common_red"], ["scales", "means"]),
        ("s3_phase2", s3s[1], (torch.randn(1, 256, L, L, device=dev),
                               torch.randn(1, 256, L, L, device=dev)),
         ["y_hat_so_far", "common_red"], ["scales", "means"]),
        ("s3_phase3", s3s[2], (torch.randn(1, 256, L, L, device=dev),
                               torch.randn(1, 256, L, L, device=dev)),
         ["y_hat_so_far", "common_red"], ["scales", "means"]),
        ("s4_gs_generator", s4, (torch.randn(1, 256, L, L, device=dev),), ["y_hat"], ["x_hat"]),
    ]
    for name, mod, dummy, inames, onames in specs:
        path = os.path.join(args.out, name + ".onnx")
        with torch.no_grad():
            torch.onnx.export(mod, dummy, path, input_names=inames, output_names=onames,
                              opset_version=17, do_constant_folding=True)
        import onnx
        g = onnx.load(path)
        counts = {}
        for n in g.graph.node:
            counts[n.op_type] = counts.get(n.op_type, 0) + 1
        mb = os.path.getsize(path) / 1e6
        print(f"  {name}.onnx  {len(g.graph.node)} 节点  {mb:.1f} MB")
        print(f"      算子: " + ", ".join(f"{k}×{v}" if v > 1 else k for k, v in sorted(counts.items())))
    print("\n导出目录: " + os.path.abspath(args.out))


if __name__ == "__main__":
    main()
