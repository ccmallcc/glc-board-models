r"""V0 基准运行器（Kodak 或任意图集）

为什么需要它：官方 test_image.py 里 DataLoader 硬编码 num_workers=24，在 Windows 上会
导致 worker 崩溃（RuntimeError: DataLoader worker exited unexpectedly）。本脚本复用官方
同一套模型与指标代码，只把 worker 数变成可配置（默认 0=主进程），便于在 Windows 上稳定复现。

用法：
  set PYTHONPATH=<repo>\src\utils
  python v0_baseline.py --repo <repo> --model <ckpt> --input <imgdir> --output <outdir>
                        --q_indexes 0 1 2 3 [--num_workers 0] [--skip_quality]
"""
import argparse
import json
import math
import os
import sys
import time

import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="GLC 仓库根目录")
    parser.add_argument("--model", required=True, help="GLC_image.pth.tar 路径")
    parser.add_argument("--input", required=True, help="输入图片目录")
    parser.add_argument("--output", required=True, help="输出目录")
    parser.add_argument("--q_indexes", type=int, nargs="+", default=[0, 1, 2, 3])
    parser.add_argument("--num_workers", type=int, default=0)
    parser.add_argument("--padding_size", type=int, default=64)
    parser.add_argument("--skip_quality", action="store_true", help="跳过 LPIPS/DISTS/FID 等指标")
    parser.add_argument("--tag", default="", help="写入报告的名称标记")
    args = parser.parse_args()

    repo = os.path.abspath(args.repo)
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "src", "utils"))

    from src.models.image_model import GLC_Image
    from src.utils.test_utils import (
        init_func, get_state_dict, from_0_1_to_minus1_1, write_image, OnlyImageFolder,
    )

    init_func()

    state = get_state_dict(args.model)
    net = GLC_Image(inplace=True)
    missing, unexpected = net.load_state_dict(state, strict=False)
    if missing or unexpected:
        print(f"[warn] state_dict 差异: missing={len(missing)} unexpected={len(unexpected)}")
        if missing[:3]:
            print("       missing 示例:", missing[:3])
    net = net.to("cuda").eval()
    device = next(net.parameters()).device

    dataset = OnlyImageFolder(args.input, padding_size=args.padding_size)
    loader = DataLoader(dataset, batch_size=1, num_workers=args.num_workers, shuffle=False)

    summary = {"tag": args.tag, "input": os.path.abspath(args.input),
               "model": os.path.abspath(args.model), "per_q": {}}

    for q in args.q_indexes:
        save_path = os.path.join(args.output, f"q{q}")
        os.makedirs(save_path, exist_ok=True)
        all_bpps, records = [], []

        for idx, (img, image_path) in enumerate(loader):
            x = from_0_1_to_minus1_1(img.to(device))
            h, w = x.shape[2], x.shape[3]
            pl, pr, pt, pb = GLC_Image.get_padding_size(h, w, args.padding_size)
            x_padded = F.pad(x, (pl, pr, pt, pb), mode="replicate")

            if device.type == "cuda":
                torch.cuda.synchronize()
            t0 = time.perf_counter()
            with torch.no_grad():
                result = net.test(x_padded, q)
            if device.type == "cuda":
                torch.cuda.synchronize()
            latency = time.perf_counter() - t0

            recon = result["x_hat"].clamp(-1, 1)
            x_hat = F.pad(recon, (-pl, -pr, -pt, -pb))
            bpp = result["bit"] / h / w
            basename = os.path.splitext(os.path.basename(image_path[0]))[0]
            out_png = os.path.join(save_path, f"{basename}.png")
            write_image(out_png, x_hat)

            all_bpps.append(bpp)
            records.append({"file": basename, "h": h, "w": w, "bpp": bpp,
                            "bpp_y": result["bit_y"] / h / w,
                            "bpp_z": result["bit_z"] / h / w,
                            "latency_s": latency})
            print(f"[q{q} {idx + 1}/{len(loader)} {basename}] bpp={bpp:.6f} "
                  f"({h}x{w}) latency={latency:.4f}s", flush=True)

        avg_bpp = float(np.mean(all_bpps))
        entry = {"avg_bpp": avg_bpp, "avg_latency_s": float(np.mean([r["latency_s"] for r in records])),
                 "num_images": len(records), "per_image": records}
        print(f"  >>> q{q} 平均 bpp = {avg_bpp:.6f}", flush=True)

        if not args.skip_quality:
            try:
                from src.utils.metric_image import evaluate_quality
                evaluate_quality(all_bpps, input_path=args.input, output_path=save_path,
                                 log_path=save_path, patch_size=-1)
                res_file = os.path.join(save_path, "res.txt")
                if os.path.exists(res_file):
                    entry["res_txt"] = open(res_file, encoding="utf-8").read().strip()
                    print("  " + entry["res_txt"], flush=True)
            except Exception as exc:  # 指标失败不阻塞主流程
                print(f"  [warn] 指标计算失败: {type(exc).__name__}: {exc}", flush=True)
                entry["quality_error"] = f"{type(exc).__name__}: {exc}"

        summary["per_q"][f"q{q}"] = entry

    report = os.path.join(args.output, "v0_report.json")
    with open(report, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print(f"\n报告已写入: {report}")


if __name__ == "__main__":
    main()
