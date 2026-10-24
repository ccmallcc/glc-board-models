r"""T3 第二批：为 precheck 报出的不支持算子（Reciprocal / Round / GatherElements）寻找替代写法

一次性验证以下候选（每个作为独立输出分支）：
  pow_neg1        1/x  → torch.pow(x, -1)            （替代 Reciprocal）
  index_select    码本查表 → torch.index_select      （替代 GatherElements，期望导出为 Gather）
  embedding       F.embedding                        （同上，另一种写法）
  slice_stride    步长切片 x[:, :, ::2, ::2]          （棋盘掩码的替代实现）
  sign_floor      sign(x)*floor(|x|+0.5)             （round 的纯算子组合替代）
  floor_plain     torch.floor                        （单独确认 Floor 是否支持）
"""
import argparse
import os

import torch
import torch.nn as nn
import torch.nn.functional as F


class RiskyOpsV2(nn.Module):
    def __init__(self, c=64):
        super().__init__()
        self.codebook = nn.Parameter(torch.randn(256, c) * 0.02)

    def forward(self, x):
        out = {}
        denom = x.abs() + 0.5
        out["pow_neg1"] = torch.pow(denom, -1.0)
        out["slice_stride"] = x[:, :, ::2, ::2]
        out["sign_floor"] = torch.sign(x) * torch.floor(torch.abs(x) + 0.5)
        out["floor_plain"] = torch.floor(x)
        logits = x.mean(dim=(2, 3))
        idx = torch.argmax(logits, dim=1, keepdim=True)
        out["index_select"] = torch.index_select(self.codebook, 0, idx.squeeze(1))
        out["embedding"] = F.embedding(idx.squeeze(1), self.codebook)
        return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    x = torch.randn(1, 64, 32, 32)
    m = RiskyOpsV2().eval()
    path = os.path.join(args.out, "risky_ops_v2.onnx")
    with torch.no_grad():
        torch.onnx.export(
            m, x, path,
            input_names=["input"],
            output_names=["pow_neg1", "slice_stride", "sign_floor", "floor_plain",
                          "index_select", "embedding"],
            opset_version=17, do_constant_folding=True,
        )
    import onnx
    g = onnx.load(path)
    counts = {}
    for n in g.graph.node:
        counts[n.op_type] = counts.get(n.op_type, 0) + 1
    print(f"risky_ops_v2.onnx: {len(g.graph.node)} 节点")
    print("  算子: " + ", ".join(f"{k}×{v}" if v > 1 else k for k, v in counts.items()))
    print("  路径: " + path)


if __name__ == "__main__":
    main()
