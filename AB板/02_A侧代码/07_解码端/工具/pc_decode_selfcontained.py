#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""pc_decode_selfcontained.py —— PC 侧**仅凭 .glc 容器**独立解码。

为什么需要它
------------
`GLC2` 容器**不存 scales/means**，只存 z 的 16 个索引（28 B）。
解码时每相位的 scales/means 必须由解码侧从 `z_hat` 重新推出来。

- 板端编码用的是 **INT8 `_ZG`** 子图
- PC 的 `decompress_glc` 用的是 **fp32** 模型

两边推出来的 scales 不同 ⇒ CDF 行不同 ⇒ 解出来全 NaN（`V16` §5 已定性）。
`V17` 的绕法是「让编码端把 scales/means 导出给解码端」——
但那是 **2 MB 的旁路数据** 配一个 316 B 的容器，约 6600×，不是可部署形态。

本脚本走 `V16` §5.3 的**推荐路 A**：解码侧也跑同一套 INT8 `_ZG` 子图
（S2 + S3p1/p2/p3，HostBackend），自己把 scales/means 推出来。
**旁路数据彻底不需要。**

实现要点
--------
1. 子图用 PC 上的 `icraft-run.exe`（HostBackend）跑；从 WSL 直接执行该 exe
   （WSL interop 实测可用），因此整个解码器是**一条命令**。
2. 子图路径与工作目录放在**不含中文**的目录下 —— Windows exe 通过 interop
   接收参数，中文路径不作为前提。
3. 胶水层用 **numpy，与板端 `glc_board_full.py` 逐行相同**（不是 torch），
   这样解码侧推出来的 scales/means 才可能与编码端逐位一致。

用法::
    python3 pc_decode_selfcontained.py --glc_dir <含 .glc 的目录> --n 4 \
        --repo <GLC> --model <ckpt> --device cuda
"""
import argparse
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import time

import numpy as np
import torch
from PIL import Image

# ---- 不含中文的落地目录（Windows exe 通过 WSL interop 访问）----
WIN_ROOT = "E:/fudanwei/pc_decode"
LIX_ROOT = "/mnt/e/fudanwei/pc_decode"
EXE = "/mnt/e/fudanwei/Icraft-3.36.1/bin/icraft-run.exe"

# ⚠️ 实测（2026-09-26）：PC 上 `compile2\*_int8\gen\` 里的 `_ZG` 与**板端在用的**
#    `/root/glc/models/*_ZG` **不是同一次编译**（.json 大小/ md5 都不同，
#    .raw 同尺寸但 md5 不同）。用错模型集会得到"后端不等价"的假结论。
#    默认用从板端拉回来的那一套（models_board）。
MODEL_SET = os.environ.get("PC_DEC_MODEL_SET", "models_board")

Z_INDEX_BITS = 14
S = 256

SUB = {
    "s2":   ("s2_int8", "s2_hyperdec_fusion", [(1, 16, 16, 768)]),
    "s3p1": ("s3p1_int8", "s3_phase1", [(1, 16, 16, 256), (1, 16, 16, 256)]),
    "s3p2": ("s3p2_int8", "s3_phase2", [(1, 16, 16, 256), (1, 16, 16, 256)]),
    "s3p3": ("s3p3_int8", "s3_phase3", [(1, 16, 16, 256), (1, 16, 16, 256)]),
}
# board_e2e.py 记录的 runtime v_id；两套后端实测一致。
# 若 dump 取不到就回退到 --log_io 现场解析。
KNOWN_VIDS = {"s2": [184], "s3p1": [178, 182], "s3p2": [178, 182], "s3p3": [178, 182]}


def to_nchw(a):
    return np.ascontiguousarray(a.transpose(0, 3, 1, 2))


def nhwc_np(t):
    return np.ascontiguousarray(t.transpose(0, 2, 3, 1))


def psnr(a, b):
    mse = float(((a - b) ** 2).mean())
    return 10 * math.log10(4.0 / max(mse, 1e-12))


class HostRunner(object):
    """在 PC 上用 HostBackend 跑 INT8 `_ZG` 子图。"""

    def __init__(self):
        self.vids = {}
        self.n_runs = 0
        self.t_sub = 0.0

    def _paths(self, key):
        d, name, shapes = SUB[key]
        w = "%s/%s/%s/gen/%s_ZG" % (WIN_ROOT, MODEL_SET, d, name)
        return w + ".json", w + ".raw", name, shapes

    def _find(self, root, vid):
        for r, _dd, fs in os.walk(root):
            c = os.path.join(r, "%d.ftmp" % vid)
            if os.path.exists(c):
                return c
        return None

    def _invoke(self, key, in_w, extra):
        qj, qr, name, _ = self._paths(key)
        # ⚠️ 实测：Python 的 execvp 直接 exec 这个 Windows PE 会报
        #    OSError: [Errno 8] Exec format error —— 没走 WSL 的 binfmt interop；
        #    而 bash 里执行同一个路径是正常的（RC=0）。所以经 bash -c 调用。
        argv = [EXE, "--json", qj, "--raw", qr, "--input", ";".join(in_w),
                "--backends", "Host"] + extra
        sh = " ".join(shlex.quote(x) for x in argv)
        t0 = time.perf_counter()
        p = subprocess.run(["/bin/bash", "-c", sh], stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, universal_newlines=True,
                           errors="replace", timeout=3600)
        self.t_sub += time.perf_counter() - t0
        self.n_runs += 1
        return p

    def __call__(self, key, inputs):
        _, _, name, shapes = self._paths(key)
        run_l = "%s/work/run_%s" % (LIX_ROOT, key)
        run_w = "%s/work/run_%s" % (WIN_ROOT, key)
        if os.path.isdir(run_l):
            shutil.rmtree(run_l)
        os.makedirs(run_l)
        in_w = []
        for i, t in enumerate(inputs):
            pl = "%s/in%d.ftmp" % (run_l, i)
            nhwc_np(t).astype(np.float32).tofile(pl)
            in_w.append("%s/in%d.ftmp" % (run_w, i))

        if key not in self.vids:
            self.vids[key] = list(KNOWN_VIDS[key])
        vids = self.vids[key]
        dump_w = run_w + "/dump"
        self._invoke(key, in_w, ["--log_path", dump_w, "--dump_format", "SFB",
                                 "--dump_ftmp", ",".join(str(v) for v in vids)])
        dump_l = run_l + "/dump"
        got = [self._find(dump_l, v) for v in vids]
        if any(g is None for g in got):
            # 回退：现场解析真实 v_id 再跑一遍
            io_w = run_w + "/io"
            self._invoke(key, in_w, ["--log_path", io_w, "--log_io"])
            vids = []
            for r, _dd, fs in os.walk(run_l + "/io"):
                for f in fs:
                    if f.endswith("_run_io.log"):
                        for ln in open(os.path.join(r, f), encoding="utf-8",
                                       errors="replace"):
                            if re.match(r"\s*Output\b", ln):
                                vids = [int(m) for m in re.findall(r"\((\d+)\|", ln)]
            if len(vids) != len(shapes):
                raise RuntimeError("%s: 拿到 %d 个 v_id %s，期望 %d"
                                   % (key, len(vids), vids, len(shapes)))
            self.vids[key] = vids
            dump_w = run_w + "/dump2"
            self._invoke(key, in_w, ["--log_path", dump_w, "--dump_format", "SFB",
                                     "--dump_ftmp", ",".join(str(v) for v in vids)])
            dump_l = run_l + "/dump2"
        outs = []
        for v, shp in zip(vids, shapes):
            fp = self._find(dump_l, v)
            if fp is None:
                raise RuntimeError("%s: 找不到 v_id %d 的输出" % (key, v))
            outs.append(to_nchw(np.fromfile(fp, dtype=np.float32).reshape(shp)))
        return outs


# ---------------- 胶水层：与板端 glc_board_full.py 逐行相同（numpy）----------------
def separate_prior(params):
    quant_step, scales, means = np.split(params, 3, axis=1)
    qs = np.maximum(quant_step, np.float32(0.5))
    return (np.float32(1.0) / qs).astype(np.float32), qs.astype(np.float32), scales, means


def conv1x1(params, w, b):
    """与板端 glc_board_full.py **逐位相同**：float64 累加后转 float32。

    理由见 glc_board_full.py 里的注释：这个卷积必须跨 BLAS 后端可复现，
    否则解码侧推出来的 scales/means 与编码端不一致，熵解码就会崩。
    """
    return (w.astype(np.float64) @ params.reshape(768, -1).astype(np.float64)
            + b.astype(np.float64)[:, None]).astype(np.float32).reshape(1, 256, 16, 16)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="/mnt/e/fudanwei/工作区/GLC-main/GLC-main")
    ap.add_argument("--model", default="/mnt/e/fudanwei/工作区/GLC-main/GLC-main/"
                                       "pretrained/GLC_image.pth.tar")
    ap.add_argument("--glc_dir", default=LIX_ROOT + "/glc")
    ap.add_argument("--png_dir", default="/mnt/e/fudanwei/工作区/testset/kodak_real")
    ap.add_argument("--consts", default=LIX_ROOT + "/consts")
    ap.add_argument("--enc_ops", default="",
                    help="[仅用于校验] 编码端导出的 _raw 操作数目录；不给就不校验")
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    repo = os.path.abspath(a.repo)
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "src", "utils"))
    import types
    stub = types.ModuleType("src.utils.metric_image")
    stub.evaluate_quality = lambda *x, **k: None
    sys.modules["src.utils.metric_image"] = stub

    import test_image_complement2 as T
    from src.models.image_model import GLC_Image
    from src.utils.test_utils import get_state_dict, init_func

    init_func()
    dev = torch.device(a.device if (a.device != "cuda" or torch.cuda.is_available())
                       else "cpu")
    model = GLC_Image(inplace=True).to(dev)
    model.load_state_dict(get_state_dict(a.model), strict=True)
    model.eval()
    em = T.build_entropy_model(dev)

    codebook = np.load(a.consts + "/z_codebook.npy")
    ysp_w = np.load(a.consts + "/ysp_reduce_w.npy").reshape(256, 768)
    ysp_b = np.load(a.consts + "/ysp_reduce_b.npy")
    R = HostRunner()

    print("设备: %s" % dev)
    print("子图: PC 本地 HostBackend（icraft-run.exe），INT8 _ZG")
    print("常量: 码本 %s  1x1 卷积 %s" % (codebook.shape, ysp_w.shape))
    print()

    pngs = sorted(f for f in os.listdir(a.png_dir) if f.lower().endswith(".png"))
    files = sorted(f for f in os.listdir(a.glc_dir) if f.endswith(".glc"))
    rows = []

    for i, fn in enumerate(files[:a.n]):
        blob = open(os.path.join(a.glc_dir, fn), "rb").read()
        q_index, dims, streams = T.parse_bitstream(blob)
        (oh, ow, ph, pw, yc, yh, yw, zc, zh, zw, zcnt) = dims
        z_payload, *y_streams = streams
        y_shape = (1, yc, yh, yw)

        t_all = time.perf_counter()

        # 1) z 索引 -> z_hat（容器里唯一带的熵参数线索）
        z_indices = T.unpack_fixed_width(z_payload, zcnt, T.Z_INDEX_BITS)
        # ⚠️ HostRunner 的入参一律是 **NCHW**（它内部自己转 NHWC 再落盘）。
        #    板端是直接写 NHWC 文件；这里必须转成 NCHW，否则会转置两次。
        z_hat = codebook[np.asarray(z_indices, dtype=np.int64)]
        z_hat = z_hat.reshape(1, 4, 4, 256).transpose(0, 3, 1, 2)
        z_hat = np.ascontiguousarray(z_hat).astype(np.float32)

        # 2) S2 (INT8, PC 本地) -> params
        (params,), = [R("s2", [z_hat])]

        # 3) 胶水：与编码端同一套 numpy 实现
        q_enc, q_dec, scales0, means0 = separate_prior(params)
        common = conv1x1(params, ysp_w, ysp_b)

        # 4) 四相位：k>=1 需要先解出前几相位 -> 顺序是本质的
        masks = model.get_mask_four_parts(*y_shape, torch.float32, dev)
        y_hat_so_far = torch.zeros(y_shape, device=dev)
        t_ent = 0.0
        enc_ok = True
        for k, (mask, stream) in enumerate(zip(masks, y_streams)):
            if k == 0:
                s_, m_ = scales0, means0
            else:
                s_, m_ = R("s3p%d" % k, [y_hat_so_far.cpu().numpy(), common])
                s_ = s_.astype(np.float32)
                m_ = m_.astype(np.float32)
            if a.enc_ops:
                od = os.path.join(a.enc_ops, "img%d" % i)
                try:
                    er_s = np.fromfile("%s/p%d_scales_raw.f32" % (od, k), dtype=np.float32)
                    er_m = np.fromfile("%s/p%d_means_raw.f32" % (od, k), dtype=np.float32)
                    ok_s = np.array_equal(er_s, s_.reshape(-1))
                    ok_m = np.array_equal(er_m, m_.reshape(-1))
                    print("    phase %d 解码侧自算 vs 编码端导出: scales %s, means %s"
                          % (k, "逐位一致" if ok_s else "**不同**",
                             "逐位一致" if ok_m else "**不同**"))
                    enc_ok &= (ok_s and ok_m)
                except Exception as e:
                    print("    phase %d 校验跳过: %s" % (k, e))
            t0 = time.perf_counter()
            dec = T.entropy_decode_stage(
                em, stream, torch.from_numpy(s_).to(dev),
                torch.from_numpy(m_).to(dev), mask)
            if isinstance(dec, (tuple, list)):
                dec = dec[0]
            t_ent += time.perf_counter() - t0
            y_hat_so_far = y_hat_so_far + T.scatter_masked(dec, mask, y_shape)
            if os.environ.get("PC_DEC_DBG"):
                dd = LIX_ROOT + "/dbg"
                os.makedirs(dd, exist_ok=True)
                # NHWC 落盘，方便与板端 run/s3p{k}/in0.ftmp 直接对拍
                nhwc_np(y_hat_so_far.cpu().numpy()).tofile(
                    "%s/%s_p%d_yh.nhwc" % (dd, fn, k))
                if k == 0:
                    nhwc_np(common).tofile("%s/%s_common.nhwc" % (dd, fn))

        y_hat = y_hat_so_far * torch.from_numpy(q_dec).to(dev)
        curr_q_dec = model.q_dec[q_index:q_index + 1]
        t0 = time.perf_counter()
        with torch.no_grad():
            rec = model.vqgan.generator(model.dec(y_hat, curr_q_dec)).clamp(-1, 1)
        if dev.type == "cuda":
            torch.cuda.synchronize(dev)
        t_s4 = time.perf_counter() - t0
        total = time.perf_counter() - t_all

        rec = rec[:, :, :oh, :ow]
        im = Image.open(os.path.join(a.png_dir, pngs[i % len(pngs)])).convert("RGB")
        w, h = im.size
        x0, y0 = (i * 37) % max(1, w - S), (i * 53) % max(1, h - S)
        px = np.asarray(im.crop((x0, y0, x0 + S, y0 + S)), dtype=np.float32) / 127.5 - 1.0
        x = torch.from_numpy(px.transpose(2, 0, 1)).unsqueeze(0).to(dev)

        rows.append(dict(glc=fn, bytes=len(blob), bpp=len(blob) * 8 / (S * S),
                         t_ent_ms=t_ent * 1000, t_s4_ms=t_s4 * 1000,
                         total_ms=total * 1000, psnr=psnr(rec, x.clamp(-1, 1)),
                         scales_match=bool(enc_ok) if a.enc_ops else None))
        r = rows[-1]
        print("  %-16s %4dB bpp=%.5f  熵解码=%5.1f  S4=%7.1f  合计=%7.1f ms  PSNR=%.2f"
              % (fn, r["bytes"], r["bpp"], r["t_ent_ms"], r["t_s4_ms"],
                 r["total_ms"], r["psnr"]))

    n = len(rows)
    agg = {k: sum(r[k] for r in rows) / n for k in
           ("bytes", "bpp", "t_ent_ms", "t_s4_ms", "total_ms", "psnr")}
    print("\n===== PC 侧自洽解码（只用容器；%s）平均 over %d =====" % (dev, n))
    print("  容器 %.1f B  bpp=%.5f  PSNR=%.2f"
          % (agg["bytes"], agg["bpp"], agg["psnr"]))
    print("  熵解码 %.1f ms + S4 %.1f ms = %.1f ms"
          % (agg["t_ent_ms"], agg["t_s4_ms"], agg["total_ms"]))
    print("  子图 HostBackend 调用 %d 次，累计 %.2f s（含进程启动）"
          % (R.n_runs, R.t_sub))
    if a.enc_ops:
        ok = all(r["scales_match"] for r in rows)
        print("  解码侧自算的 scales/means vs 编码端导出: %s"
              % ("**全部逐位一致**" if ok else "**有差异**"))
    if a.out:
        import json
        json.dump(dict(rows=rows, agg=agg, device=str(dev),
                       sub_calls=R.n_runs, sub_s=R.t_sub),
                  open(a.out, "w"), indent=2, ensure_ascii=False, default=float)
        print("  报告:", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
