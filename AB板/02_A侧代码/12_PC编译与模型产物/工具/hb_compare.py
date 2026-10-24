r"""HostBackend 数值对拍：读取 icraft dump 的 ftmp，与 PyTorch 参考量比较

ftmp(SFB) 为**无头裸二进制**、fp32、NHWC 布局，文件名即 v_id。
"""
import argparse
import glob
import os

import numpy as np
from PIL import Image


def load_ftmp(path, shape):
    raw = np.fromfile(path, dtype=np.float32)
    if raw.size != int(np.prod(shape)):
        raise ValueError(f"{os.path.basename(path)} 元素数 {raw.size} != 期望 {int(np.prod(shape))} ({shape})")
    return raw.reshape(shape)


def stats(name, a, b):
    d = np.abs(a - b)
    denom = np.maximum(np.abs(b), 1e-6)
    print(f"  {name}")
    print(f"     形状 {a.shape}  | 参考范围 [{b.min():.4f}, {b.max():.4f}]  mean={b.mean():.6f} std={b.std():.6f}")
    print(f"     最大绝对误差 = {d.max():.3e}   平均绝对误差 = {d.mean():.3e}")
    print(f"     最大相对误差 = {(d / denom).max():.3e}   余弦相似度 = "
          f"{float((a.ravel() @ b.ravel()) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12)):.8f}")
    ok = d.max() < 1e-3 * max(1.0, np.abs(b).max())
    print("     判定: " + ("✅ 一致" if ok else "⚠️ 存在差异"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", required=True, help="ftmpSFB 目录")
    ap.add_argument("--ref", required=True, help="PyTorch 参考量目录（.npy）")
    ap.add_argument("--png", help="输入图片，用于核对预处理约定")
    args = ap.parse_args()

    print("=== 0) 核对输入预处理（v_id 0）===")
    if args.png and os.path.exists(os.path.join(args.dump, "0.ftmp")):
        ic_in = load_ftmp(os.path.join(args.dump, "0.ftmp"), (1, 256, 256, 3))
        px = np.array(Image.open(args.png).convert("RGB")).astype(np.float32)   # (256,256,3) uint8
        cand = {
            "(p-127.5)*2/255": (px - 127.5) * (2.0 / 255.0),
            "p*2/255-1":       px * (2.0 / 255.0) - 1.0,
            "p/255":           px / 255.0,
            "p":               px,
        }
        for k, v in cand.items():
            err = np.abs(ic_in[0] - v).max()
            print(f"     候选 {k:18s} 最大误差 = {err:.3e}" + ("   ← 命中 ✅" if err < 1e-4 else ""))
        print(f"     icraft 实际输入范围 [{ic_in.min():.4f}, {ic_in.max():.4f}]")
    print()

    print("=== 1) 输出对拍 ===")
    targets = [("1356", "ref_s1_y.npy", (1, 16, 16, 256), (1, 256, 16, 16), "y (latent 16x16x256)"),
               ("1358", "ref_s1_z.npy", (1, 4, 4, 256), (1, 256, 4, 4), "z (hyper 4x4x256)")]
    for vid, refname, ic_shape, pt_shape, label in targets:
        p = os.path.join(args.dump, f"{vid}.ftmp")
        rp = os.path.join(args.ref, refname)
        if not os.path.exists(p):
            print(f"  [跳过] 缺 {vid}.ftmp")
            continue
        if not os.path.exists(rp):
            print(f"  [跳过] 缺 {refname}")
            continue
        ic = load_ftmp(p, ic_shape)                       # NHWC
        ic_nchw = np.transpose(ic, (0, 3, 1, 2))          # -> NCHW
        ref = np.load(rp)
        if ic_nchw.shape != ref.shape:
            print(f"  [形状不符] icraft {ic_nchw.shape} vs 参考 {ref.shape}")
            continue
        print(f"  ── {label} ──")
        stats(f"icraft(v_id {vid}) vs PyTorch", ic_nchw, ref)
        print()


if __name__ == "__main__":
    main()
