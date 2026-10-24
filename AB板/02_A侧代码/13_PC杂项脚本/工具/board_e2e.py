# -*- coding: utf-8 -*-
r"""GLC 边端编码链路 —— **真板 NPU 本地执行**版。

与 `quant_e2e.py` 的区别只有一个，但是决定性的：

    quant_e2e.py  : icraft-run.exe **在 PC 上**，后端 Host（CPU 仿真）
    board_e2e.py  : icraft-run   **在板子上**，后端 ``ZG330,axi://zg330aiu``（真 NPU）
                    —— 推理全程不经过网络；网络只用来搬输入/输出张量。

链路（与 quant_e2e 完全一致，只是每个子图换到板子上算）::

    x --S1--> y, z            (板 NPU)
    z_hat = vq(z)             (PC)
    z_hat --S2--> params      (板 NPU)
    q_enc,q_dec,scales0,means0 = separate_prior(params)   (PC)
    common = y_spatial_prior_reduction(params)            (PC)
    k=0            : scales0/means0 直接用
    k=1,2,3        : (y_hat_so_far, common) --S3p{k}--> scales, means  (板 NPU)
    y_hat = y_hat_so_far * q_dec                          (PC)
    y_hat --S4--> x_hat                                   (PC, fp32)

口径（**必须一起引用，否则没意义**）：

    hard_ms      板上 NPU 真实计算时间（官方 total_hard_time，逐子图求和）
    proc_wall_ms icraft-run 进程墙钟（**含每次重新载模型**，见报告）
    load_ms      Load Json + Load Raw
    tx_ms        张量过网线的时间（PC<->板）
    dec_ms       PC 侧解码（rANS 解 + S4 fp32）

用法::

    python board_e2e.py --repo <GLC> --model <ckpt> --n 4 --q 0
"""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time

import numpy as np
import torch
from PIL import Image

# ---------------------------------------------------------------- 常量
SPECS = {
    "s1":   ("s1_encoder_ga_hyper", [(1, 16, 16, 256), (1, 4, 4, 256)]),
    "s2":   ("s2_hyperdec_fusion",  [(1, 16, 16, 768)]),
    "s3p1": ("s3_phase1",           [(1, 16, 16, 256), (1, 16, 16, 256)]),
    "s3p2": ("s3_phase2",           [(1, 16, 16, 256), (1, 16, 16, 256)]),
    "s3p3": ("s3_phase3",           [(1, 16, 16, 256), (1, 16, 16, 256)]),
}
ORDER = ["s1", "s2", "s3p1", "s3p2", "s3p3"]
SCALE_MIN = 0.11          # test_image_complement2.SCALE_MIN

# runtime 输出 v_id：运行时**重新编号**，不能跨图硬编码 ——
# 这几个值由 `compile_real/batch_summary.json`（HostBackend 实跑）+ 板上
# `--log_io` 各验证过一次，实测两套后端完全一致（见报告 §口径）。
# 仍保留「dump 缺失就自动回退到 --log_io 现场解析」的保险。
KNOWN_VIDS = {"s1": [3310, 3314], "s2": [184],
              "s3p1": [178, 182], "s3p2": [178, 182], "s3p3": [178, 182]}

# ⭐ 关键部署参数：默认 -1 会在加载时**逐一评估三套 OCM 方案**，
# S1（829 算子）因此多花 ~15 s，而选出来的方案与方案一等效。
# 钉住 1 → 墙钟 20.4 s 降到 6.0 s，NPU 硬计算时间不变（346.6 ms）。
OCMOPT = 1


def nhwc(t):
    return np.ascontiguousarray(t.detach().cpu().numpy().transpose(0, 2, 3, 1))


def to_nchw(a):
    return torch.from_numpy(np.ascontiguousarray(a.transpose(0, 3, 1, 2)))


class Board:
    """通过 ssh/scp 驱动板子上的 icraft-run（本地 AXI 设备）。"""

    def __init__(self, host, key, remote_models, remote_run, stage):
        self.host = host
        self.key = os.path.expanduser(key)
        self.remote_models = remote_models
        self.remote_run = remote_run
        self.stage = stage
        self.opts = ["-i", self.key, "-o", "StrictHostKeyChecking=no",
                     "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
                     "-o", "BatchMode=yes"]
        self.vid_cache = {}
        self.n_runs = 0
        self.tx_s = 0.0
        os.makedirs(stage, exist_ok=True)

    # -- 低层 --------------------------------------------------------
    def ssh(self, cmd, timeout=600):
        return subprocess.run(["ssh"] + self.opts + ["root@" + self.host, cmd],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout)

    def _scp(self, local, remote, up=True, timeout=600):
        src, dst = (local, "root@%s:%s" % (self.host, remote)) if up else \
                   ("root@%s:%s" % (self.host, remote), local)
        t0 = time.perf_counter()
        p = subprocess.run(["scp"] + self.opts + [src, dst], capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout)
        self.tx_s += time.perf_counter() - t0
        if p.returncode != 0:
            raise RuntimeError("scp failed: %s\n%s" % (src, p.stderr[-400:]))

    # -- 一次子图前向 ------------------------------------------------
    def run(self, key, inputs):
        name = SPECS[key][0]
        rd = "%s/%s" % (self.remote_run, key)
        ld = os.path.join(self.stage, key)
        os.makedirs(ld, exist_ok=True)
        self.ssh("mkdir -p %s" % rd)

        ipaths = []
        for i, t in enumerate(inputs):
            p = os.path.join(ld, "in%d.ftmp" % i)
            nhwc(t).astype(np.float32).tofile(p)
            ipaths.append(p)
        for p in ipaths:
            self._scp(p, rd + "/", up=True)

        # v_id：优先用已知表（省掉一次昂贵的 --log_io 全特征图导出），
        # 若 dump 拉不回来再回退到 --log_io 现场解析。
        if key not in self.vid_cache:
            self.vid_cache[key] = list(KNOWN_VIDS[key])
        vids = self.vid_cache[key]

        tm = self._run_once(rd, name, ipaths, dump_vids=vids, do_io=False)

        outs, got = [], 0
        for v in vids:
            self._scp("%s/%d.ftmp" % (ld, v),
                      "%s/logs/%s/ftmpSFB/%d.ftmp" % (rd, name, v), up=False)
        for v, shp in zip(vids, SPECS[key][1]):
            fp = os.path.join(ld, "%d.ftmp" % v)
            if not os.path.exists(fp):
                break
            got += 1
            outs.append(to_nchw(np.fromfile(fp, dtype=np.float32).reshape(shp)))
        if got != len(vids):
            # 回退：现场解析真实的 runtime v_id，再跑一遍
            self._run_once(rd, name, ipaths, dump_vids=None, do_io=True)
            vids = self._parse_vids(rd, name)
            self.vid_cache[key] = vids
            tm = self._run_once(rd, name, ipaths, dump_vids=vids, do_io=False)
            outs = []
            for v in vids:
                self._scp("%s/%d.ftmp" % (ld, v),
                          "%s/logs/%s/ftmpSFB/%d.ftmp" % (rd, name, v), up=False)
            for v, shp in zip(vids, SPECS[key][1]):
                outs.append(to_nchw(np.fromfile(
                    os.path.join(ld, "%d.ftmp" % v), dtype=np.float32).reshape(shp)))
        tm["vids"] = vids
        tm["fallback"] = bool(got != len(vids))
        return outs, tm

    def _run_once(self, rd, name, ipaths, dump_vids, do_io):
        rlist = [os.path.basename(p) for p in ipaths]
        inner = ("/usr/bin/icraft-run --json %s_ZG.json --raw %s_ZG.raw "
                 "--input \"%s\" --backends 'ZG330,axi://zg330aiu;Host' "
                 "--log_path logs --log_time --ocmopt %d%s%s"
                 % (self.remote_models + "/" + name, self.remote_models + "/" + name,
                    ";".join(rlist), OCMOPT,
                    " --log_io" if do_io else "",
                    (" --dump_format SFB --dump_ftmp " + ",".join(str(v) for v in dump_vids))
                    if dump_vids else ""))
        # 墙钟在**板内**测，避免被 ssh 启动开销污染
        cmd = ("cd %s && rm -rf logs && mkdir -p logs && "
               "S=$(date +%%s%%N); %s > /tmp/_brun.txt 2>&1; RC=$?; E=$(date +%%s%%N); "
               "echo \"BOARD_WALL_MS=$(( (E-S)/1000000 ))\"; echo \"BOARD_RC=$RC\"; "
               "cat /tmp/_brun.txt" % (rd, inner))
        t0 = time.perf_counter()
        p = self.ssh(cmd)
        rtt = time.perf_counter() - t0
        self.n_runs += 1
        out = p.stdout
        g = lambda pat: (float(re.search(pat, out).group(1))
                         if re.search(pat, out) else float("nan"))
        return dict(rc=p.returncode, rtt_ms=rtt * 1000.0,
                    wall_ms=g(r"BOARD_WALL_MS=(\d+)"),
                    hard_ms=g(r"total_hard_time:\s*([0-9.]+)"),
                    backbone_ms=g(r"total_backbone_time:\s*([0-9.]+)"),
                    load_json_ms=g(r"Load Json Time:\s*([0-9.]+)"),
                    load_raw_ms=g(r"Load Raw Time:\s*([0-9.]+)"),
                    icore=(re.search(r"icore:\s*(.+)", out).group(1).strip()
                           if re.search(r"icore:\s*(.+)", out) else ""),
                    raw=out)

    def _parse_vids(self, rd, name):
        p = self.ssh("grep -h '^Output' %s/logs/%s/*_run_io.log | head -1" % (rd, name))
        return [int(m) for m in re.findall(r"\((\d+)\|", p.stdout)]


def psnr(a, b):
    mse = float(((a - b) ** 2).mean())
    return 10 * math.log10(4.0 / max(mse, 1e-12))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--host", default="192.168.31.72")
    ap.add_argument("--key", default="~/.ssh/id_board")
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--q", type=int, default=0)
    ap.add_argument("--png_dir", default=r"E:\fudanwei\工作区\testset\kodak_real")
    ap.add_argument("--out", default=r"E:\fudanwei\工作区\_board_run\e2e")
    ap.add_argument("--no_dump_operands", action="store_true",
                    help="不导出 glc2_pack 的输入（符号/scale/z 索引）")
    a = ap.parse_args()
    a.dump_operands = not a.no_dump_operands

    os.makedirs(a.out, exist_ok=True)
    B = Board(a.host, a.key, "/root/glc/models", "/root/glc/run",
              r"E:\fudanwei\_board_run\stage")

    repo = os.path.abspath(a.repo)
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "src", "utils"))
    from src.models.image_model import GLC_Image
    from src.utils.test_utils import get_state_dict

    model = GLC_Image(inplace=True)
    model.load_state_dict(get_state_dict(a.model), strict=True)
    model.eval()

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "c1exp", r"E:\fudanwei\工作区\tools\c1_export_subgraphs.py")
    exp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exp)
    exp.patch_attention_to_full(repo, model)

    # 先确认板子就绪
    h = B.ssh("hostname; uname -m; pgrep -f 'icraft[-]serve' >/dev/null && echo SERVE_RUNNING || echo NO_SERVE")
    print("板子:", h.stdout.strip().replace("\n", " | "))
    print("设备: 本地 axi://zg330aiu（推理不经过网络）")
    print()

    pngs = sorted(f for f in os.listdir(a.png_dir) if f.lower().endswith(".png"))
    S = a.size
    rows = []
    chain_t = {}

    for i in range(a.n):
        im = Image.open(os.path.join(a.png_dir, pngs[i % len(pngs)])).convert("RGB")
        w, hgt = im.size
        x0, y0 = (i * 37) % max(1, w - S), (i * 53) % max(1, hgt - S)
        px = np.asarray(im.crop((x0, y0, x0 + S, y0 + S)), dtype=np.float32) / 127.5 - 1.0
        x = torch.from_numpy(px.transpose(2, 0, 1)).unsqueeze(0).contiguous()

        timings = {}
        with torch.no_grad():
            ref = model.test(x, a.q)
            bit_fp32 = ref["bit"]
            curr_q_enc = model.q_enc[a.q:a.q + 1]
            curr_q_dec = model.q_dec[a.q:a.q + 1]

            t0 = time.perf_counter()
            (y, z), timings["s1"] = B.run("s1", [x])
            z_idx = model.z_vq.get_indices(z)
            z_hat_flat = model.z_vq.get_quan_feat(
                z_idx, (z.shape[0], z.shape[2], z.shape[3], z.shape[1]))
            (params,), timings["s2"] = B.run("s2", [z_hat_flat])

            q_enc, q_dec, scales0, means0 = model.separate_prior(params)
            common = model.y_spatial_prior_reduction(params)

            masks = model.get_mask_four_parts(*y.shape, y.dtype, y.device)
            y_scaled = y * q_enc
            y_hat_so_far = torch.zeros_like(y)
            bits_y = 0.0
            phase_ops = []
            phase_priors = []
            for k, mask in enumerate(masks):
                if k == 0:
                    s_, m_ = scales0, means0
                else:
                    key = "s3p%d" % k
                    (s_, m_), timings[key] = B.run(key, [y_hat_so_far, common])
                _res, y_q, y_hat_k, sc_hat = model.process_with_mask(
                    y_scaled, s_, m_, mask)
                bits_y += float(model.get_y_gaussian_bits(y_q, sc_hat).sum())
                phase_ops.append((y_q, sc_hat))
                phase_priors.append((s_, m_))
                y_hat_so_far = y_hat_so_far + y_hat_k
            enc_wall = time.perf_counter() - t0
            y_hat = y_hat_so_far * q_dec

            # ---- PC 侧解码（S4 fp32）----
            td0 = time.perf_counter()
            x_hat = model.vqgan.generator(model.dec(y_hat, curr_q_dec))
            dec_wall = time.perf_counter() - td0
            x_hat = x_hat.clamp(-1, 1)
            x_fp32 = ref["x_hat"].clamp(-1, 1)

        # ---- 导出操作数，供板端 CPU 熵编码器 glc2_pack 使用 ----
        # ⚠️ 口径必须与 test_image_complement2.entropy_encode_stage 完全一致：
        #     y_values     = compact_masked(y_scaled, mask)   ← 只取未屏蔽位置，16384/phase
        #     stage_scales = compact_masked(scales, mask).clamp_min(0.11)
        #     stage_means  = compact_masked(means, mask)
        #     sym          = round(y_values - stage_means)
        # 早期版本错导出了全部 65536 个位置（屏蔽处 scale=0），
        # 那会得到"能过校验但不是真编解码器产出"的码流。
        if a.dump_operands:
            def _compact(t, mk):
                b, c, h, w = t.shape
                return t[mk.expand_as(t).bool()].reshape(1, c, h, w // 4)

            od = os.path.join(a.out, "operands", "img%d" % i)
            os.makedirs(od, exist_ok=True)
            for k, mask in enumerate(masks):
                s_raw, m_raw = phase_priors[k]
                yv = _compact(y_scaled, mask)
                sm = _compact(s_raw, mask).clamp_min(SCALE_MIN)
                mn = _compact(m_raw, mask)
                sym = torch.round(yv - mn).to(torch.int32).reshape(-1).cpu().numpy()
                sym.tofile(os.path.join(od, "p%d_sym.i32" % k))
                sm.reshape(-1).to(torch.float32).cpu().numpy().tofile(
                    os.path.join(od, "p%d_scales.f32" % k))
                # 解码端必须重算 scales/means；这里把它们**整张**存下来，
                # 供 PC 侧解码复用（值逐位相同，见报告 §5 论证）
                s_raw.reshape(-1).to(torch.float32).cpu().numpy().tofile(
                    os.path.join(od, "p%d_scales_raw.f32" % k))
                m_raw.reshape(-1).to(torch.float32).cpu().numpy().tofile(
                    os.path.join(od, "p%d_means_raw.f32" % k))
            z_np = z_idx.detach().cpu().numpy().astype(np.int32).ravel()
            z_np.tofile(os.path.join(od, "z_indices.i32"))
            yc, yh, yw = y.shape[1], y.shape[2], y.shape[3]
            zc, zh, zw = z.shape[1], z.shape[2], z.shape[3]
            with open(os.path.join(od, "hdr.txt"), "w", encoding="utf-8") as f:
                f.write("# GLC2 header fields, board-NPU chain, sample %d (%s)\n"
                        % (i, pngs[i % len(pngs)]))
                f.write("MAGIC GLC2\nVERSION 2\n")
                f.write("Q_INDEX %d\nFLAGS 0\n" % a.q)
                for k_, v_ in (("ORIG_H", S), ("ORIG_W", S),
                               ("PAD_H", S), ("PAD_W", S),
                               ("Y_C", yc), ("Y_H", yh), ("Y_W", yw),
                               ("Z_C", zc), ("Z_H", zh), ("Z_W", zw)):
                    f.write("%s %d\n" % (k_, v_))
                f.write("Z_COUNT %d\n" % z_np.size)
                f.write("SOURCE %s\n" % pngs[i % len(pngs)])
                # 参考长度由板端多轮补齐（glc2_pack 是验证工具，不符不出容器）
                f.write("STAGE0_LEN 0\nSTAGE1_LEN 0\nSTAGE2_LEN 0\nSTAGE3_LEN 0\n")
                f.write("REF_BYTES 0\nREF_MD5 0\n")
            np.save(os.path.join(od, "ref_yhat.npy"), y_hat.detach().cpu().numpy())
            np.save(os.path.join(od, "ref_xhat.npy"), x_hat.detach().cpu().numpy())

        hard = sum(timings[k]["hard_ms"] for k in ORDER)
        wall = sum(timings[k]["wall_ms"] for k in ORDER)
        load = sum(timings[k]["load_json_ms"] + timings[k]["load_raw_ms"] for k in ORDER)
        r = dict(sample=i, png=pngs[i % len(pngs)],
                 npu_hard_ms=hard, sub_hard={k: timings[k]["hard_ms"] for k in ORDER},
                 proc_wall_ms=wall, sub_wall={k: timings[k]["wall_ms"] for k in ORDER},
                 sub_load={k: round(timings[k]["load_json_ms"] +
                                    timings[k]["load_raw_ms"], 1) for k in ORDER},
                 load_ms=load, enc_wall_ms=enc_wall * 1000,
                 pc_dec_ms=dec_wall * 1000,
                 fallback=[k for k in ORDER if timings[k].get("fallback")],
                 bits_y=bits_y,
                 bits_z=float(z.shape[2] * z.shape[3] * math.log2(model.codebook_size)),
                 bits_theory=bits_y + z.shape[2] * z.shape[3]
                 * math.log2(model.codebook_size),
                 bpp_theory=(bits_y + z.shape[2] * z.shape[3]
                             * math.log2(model.codebook_size)) / (S * S),
                 psnr_board=psnr(x_hat, x), psnr_fp32=psnr(x_fp32, x))
        rows.append(r)
        print("  %-12s NPU=%.2fms  进程=%.0fms  载模型=%.0fms  PC解码=%.1fms  "
              "bpp=%.5f PSNR=%.2f"
              % (r["png"], r["npu_hard_ms"], r["proc_wall_ms"],
                 r["load_ms"], r["pc_dec_ms"], r["bpp_theory"], r["psnr_board"]))

    n = len(rows)
    agg = dict(
        n=n,
        npu_hard_ms=sum(r["npu_hard_ms"] for r in rows) / n,
        sub_hard={k: sum(r["sub_hard"][k] for r in rows) / n for k in ORDER},
        sub_wall={k: sum(r["sub_wall"][k] for r in rows) / n for k in ORDER},
        sub_load={k: sum(r["sub_load"][k] for r in rows) / n for k in ORDER},
        proc_wall_ms=sum(r["proc_wall_ms"] for r in rows) / n,
        load_ms=sum(r["load_ms"] for r in rows) / n,
        enc_wall_ms=sum(r["enc_wall_ms"] for r in rows) / n,
        pc_dec_ms=sum(r["pc_dec_ms"] for r in rows) / n,
        bpp_theory=sum(r["bpp_theory"] for r in rows) / n,
        psnr_board=sum(r["psnr_board"] for r in rows) / n,
        psnr_fp32=sum(r["psnr_fp32"] for r in rows) / n,
        tx_total_s=B.tx_s, runs=B.n_runs, vids=B.vid_cache)
    print("\n===== 平均 over %d 图 =====" % n)
    print("  板上 NPU 硬计算   : %.2f ms   %s" % (agg["npu_hard_ms"],
          {k: round(v, 3) for k, v in agg["sub_hard"].items()}))
    print("  逐子图进程墙钟    : %s" % {k: round(v) for k, v in agg["sub_wall"].items()})
    print("  逐子图载模型      : %s" % {k: round(v) for k, v in agg["sub_load"].items()})
    print("  icraft-run 进程墙钟: %.0f ms（含每次重新载模型 %.0f ms）"
          % (agg["proc_wall_ms"], agg["load_ms"]))
    print("  PC 侧解码(S4 fp32) : %.1f ms" % agg["pc_dec_ms"])
    print("  理论 bpp=%.5f  PSNR(板)=%.2f  PSNR(fp32)=%.2f"
          % (agg["bpp_theory"], agg["psnr_board"], agg["psnr_fp32"]))
    print("  传输合计 %.1f s / %d 次板端进程" % (agg["tx_total_s"], agg["runs"]))
    json.dump(dict(rows=rows, agg=agg),
              open(os.path.join(a.out, "board_e2e.json"), "w"), indent=2, ensure_ascii=False)
    print("  报告: %s" % os.path.join(a.out, "board_e2e.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
