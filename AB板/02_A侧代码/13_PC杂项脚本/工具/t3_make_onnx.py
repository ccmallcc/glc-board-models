r"""T3：构造 GroupNorm 相关的最小 ONNX 模型，用于 Icraft precheck 实测

产出（到 out_dir）：
  gn_only.onnx        仅含 nn.GroupNorm(32,128,eps=1e-6)          —— 官方写法
  gn_rewrite.onnx     等价改写：Reshape/Transpose + InstanceNorm2d + Mul/Add
  risky_ops.onnx      argmin / gather / 张量除法 / round 等风险算子的探测模型
并打印每个 ONNX 的算子清单，便于人工核对。
"""
import argparse
import os
import sys

import torch
import torch.nn as nn


class GNOnly(nn.Module):
    """GLC 里的真实用法：num_groups=32, channels=128, eps=1e-6, affine=True"""

    def __init__(self, c=128, g=32):
        super().__init__()
        self.gn = nn.GroupNorm(num_groups=g, num_channels=c, eps=1e-6, affine=True)

    def forward(self, x):
        return self.gn(x)


class GNRewrite(nn.Module):
    """等价改写：把组内 C/G 个通道搬到 W 轴，用 InstanceNorm2d 归一化

    GroupNorm(G) 的归一化域是每样本每组 (C/G, H, W)；
    InstanceNorm2d 对 (N,H,W,C) 按 (1,H,W,1) 切片在 H×W 上统计，
    因此把 C/G 折进 W 轴后二者归一化域完全一致。
    """

    def __init__(self, c=128, g=32, eps=1e-6):
        super().__init__()
        self.g, self.c, self.eps = g, c, eps
        self.inorm = nn.InstanceNorm2d(1, eps=eps, affine=False)
        self.gamma = nn.Parameter(torch.ones(c))
        self.beta = nn.Parameter(torch.zeros(c))

    def forward(self, x):
        n, c, h, w = x.shape
        gs = c // self.g
        xr = x.reshape(n, self.g, gs, h, w).permute(0, 1, 3, 2, 4)   # (N,G,H,C/G,W)
        xr = xr.reshape(n * self.g, h, gs * w).unsqueeze(1)          # (N*G,1,H,W*C/G)
        xn = self.inorm(xr)
        xn = xn.squeeze(1).reshape(n, self.g, h, gs, w).permute(0, 1, 3, 2, 4)
        xn = xn.reshape(n, c, h, w)
        return xn * self.gamma.view(1, c, 1, 1) + self.beta.view(1, c, 1, 1)


class RiskyOps(nn.Module):
    """把几个"文档层面存疑"的算子拼在一个模型里，一次 parse 全测出来"""

    def __init__(self, c=64):
        super().__init__()
        self.codebook = nn.Parameter(torch.randn(256, c) * 0.02)  # 小码本便于导出

    def forward(self, x):
        out = {}
        # 1) 张量除法（GLC: q_enc = 1./quant_step）
        denom = x.abs() + 0.5
        out["tensor_div"] = x / denom
        # 2) 张量取倒数再乘（候选改写方案）
        out["recip_mul"] = x * (1.0 / denom)
        # 3) round（GLC 编码端需要）
        out["round"] = torch.round(x * 8.0)
        # 4) argmin（VQ-E 码本检索）
        logits = x.mean(dim=(2, 3))                       # (N,C)
        out["argmin"] = torch.argmin(logits, dim=1).float()
        # 5) gather（VQ-D 码本查表）
        idx = torch.argmax(logits, dim=1, keepdim=True)   # (N,1)
        out["gather"] = torch.gather(self.codebook, 0, idx).mean(dim=1)
        # 6) 逐元素乘 + 广播（掩码/量化步长）
        out["bcast_mul"] = x * torch.ones(1, x.shape[1], 1, 1, device=x.device) * 1.5
        return out


def export(module, dummy, path, input_names, output_names):
    module.eval()
    with torch.no_grad():
        torch.onnx.export(
            module, dummy, path,
            input_names=input_names, output_names=output_names,
            opset_version=17, do_constant_folding=True,
        )
    return path


def show_ops(path):
    import onnx
    m = onnx.load(path)
    onnx.checker.check_model(m)
    ops = []
    for n in m.graph.node:
        if n.op_type not in ops:
            ops.append(n.op_type)
    counts = {}
    for n in m.graph.node:
        counts[n.op_type] = counts.get(n.op_type, 0) + 1
    print(f"  {os.path.basename(path)}: {len(m.graph.node)} 节点")
    print("    算子: " + ", ".join(f"{k}×{v}" if v > 1 else k for k, v in counts.items()))
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    x = torch.randn(1, 128, 64, 64)

    print("=== 0) 数值等价性自检：GroupNorm vs 改写方案 ===")
    gn = GNOnly()
    rw = GNRewrite()
    with torch.no_grad():
        rw.gamma.copy_(gn.gn.weight)
        rw.beta.copy_(gn.gn.bias)
        y1, y2 = gn(x), rw(x)
    diff = (y1 - y2).abs().max().item()
    print(f"  最大绝对误差 = {diff:.3e}  相对尺度 = {y1.abs().mean().item():.4f}")
    print("  → " + ("✅ 等价（可放心改写）" if diff < 1e-4 else "❌ 不等价，需排查"))

    print("\n=== 1) 导出 ONNX ===")
    p1 = export(GNOnly(), x, os.path.join(args.out, "gn_only.onnx"), ["input"], ["output"])
    p2 = export(GNRewrite(), x, os.path.join(args.out, "gn_rewrite.onnx"), ["input"], ["output"])
    xr = torch.randn(1, 64, 32, 32)
    p3 = export(RiskyOps(), xr, os.path.join(args.out, "risky_ops.onnx"), ["input"],
                ["tensor_div", "recip_mul", "round", "argmin", "gather", "bcast_mul"])

    print("\n=== 2) ONNX 算子清单（人工核对用）===")
    show_ops(p1)
    show_ops(p2)
    show_ops(p3)

    print("\n导出目录: " + os.path.abspath(args.out))


if __name__ == "__main__":
    main()
