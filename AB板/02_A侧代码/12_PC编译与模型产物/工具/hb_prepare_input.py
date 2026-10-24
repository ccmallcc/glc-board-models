r"""准备 HostBackend 对拍所需的输入：256×256 PNG + 对应的 PyTorch 参考量

产出（到 --out）：
  input_256.png      给 icraft-run --input 用的图片（NHWC uint8 → 声明 fp32）
  ref_s1_y.npy / ref_s1_z.npy   PyTorch 侧 S1 的输出（供后续比对）
  input_x.npy         PyTorch 侧实际输入张量（NCHW, [-1,1]，与模型 test() 一致）
"""
import argparse
import os
import sys

import numpy as np
import torch
from PIL import Image


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--image", required=True, help="任意图片，会被缩放到 256x256")
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", type=int, default=256)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    repo = os.path.abspath(args.repo)
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "src", "utils"))

    # 1) 造一张 256x256 PNG（给 icraft 当输入）
    img = Image.open(args.image).convert("RGB").resize((args.size, args.size), Image.BICUBIC)
    png = os.path.join(args.out, f"input_{args.size}.png")
    img.save(png)
    print(f"图片已保存: {png}  尺寸={img.size}")

    # 2) 同一张图转成 PyTorch 张量（NCHW, [-1,1]），并跑 S1 拿到参考输出
    arr = np.array(img).transpose(2, 0, 1).astype(np.float32) / 255.0
    x01 = torch.as_tensor(arr).unsqueeze(0)                    # (1,3,H,W) in [0,1]
    x = (x01 - 0.5) * 2.0                                      # [-1,1]，与 from_0_1_to_minus1_1 一致
    np.save(os.path.join(args.out, "input_x.npy"), x.numpy())
    print(f"输入张量: {tuple(x.shape)}  范围 [{x.min():.3f}, {x.max():.3f}]")

    from src.models.image_model import GLC_Image
    from src.utils.test_utils import get_state_dict

    model = GLC_Image(inplace=True)
    model.load_state_dict(get_state_dict(args.model), strict=True)
    model.eval()

    with torch.no_grad():
        y_ori = model.vqgan.encoder(x)
        y = model.enc(y_ori, model.q_enc[0:1])
        z = model.hyper_enc(y)
    for name, t in (("ref_s1_y", y), ("ref_s1_z", z)):
        np.save(os.path.join(args.out, name + ".npy"), t.numpy())
        print(f"{name}: {tuple(t.shape)}  mean={t.mean():.6f} std={t.std():.6f}")
    print("参考量已保存到:", os.path.abspath(args.out))


if __name__ == "__main__":
    main()
