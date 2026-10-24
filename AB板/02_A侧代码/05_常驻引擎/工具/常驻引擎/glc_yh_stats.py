#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""glc_yh_stats.py —— 批量编码 7 张照片，并统计每张的 **y_hat**（送进 S4 的那个张量）

为什么要它
----------
B 那边实测：同一个 int8 S4 模型，**他们自己的容器 20.8 dB，我们的容器 9.99 dB** ⇒ 对输入分布极敏感。
三套标定集的 y_hat 都在 **±3 以内**（本地已实测）。所以只要算出我们 7 张图的 y_hat 分布，
就能直接判断"是不是落在 int8 的标定范围之外"。

怎么拿到 y_hat（不改 glc_board_full.py 一行）
-------------------------------------------
`glc_board_full.py` 的 [5/6] 会把每相位的操作数落盘（`p{k}_sym.i32`、`p{k}_means_raw.f32`）+
`params.npy`，而 y_hat 可以**精确重建**：

    y_hat_so_far = Σ_k scatter( compact(means_raw_k) + sym_k , mask_k )
    y_hat        = y_hat_so_far * q_dec          # q_dec = max(quant_step, 0.5)

这与 L362-366 的算法逐行对应：
    掩码内: means_hat=m, y_res=y_scaled-m, y_q=round(...)=sym, y_hat=sym+m
    掩码外: means_hat=0, y_res=0,             y_q=0,              y_hat=0

做法：把 `glc_rsd_cpu.pl_encode_cpu` 包一层，在它之前先把 y_hat 统计出来。
"""
import hashlib
import os
import shutil
import sys
import time

import numpy as np

sys.path.insert(0, "/root/glc")
sys.path.insert(0, "/root")

import glc_board_full as G          # noqa: E402
import glc_rsd                      # noqa: E402
import glc_rsd_cpu                  # noqa: E402

IN0 = "/root/glc/run/s1/in0.ftmp"
PLGLC = "/root/glc/pack/full_img0.glc"
OUTCSV = "/root/glc/yh_stats.tsv"

_engine = None
_cur = {"name": "?"}
_rows = []


# ---------------------------------------------------------------- y_hat 重建
def compact(t, mb):
    return t[np.broadcast_to(mb, t.shape)]


def scatter(vals, mb, shape):
    out = np.zeros(shape, dtype=np.float32)
    out[np.broadcast_to(mb, shape)] = np.asarray(vals, dtype=np.float32).reshape(-1)
    return out


def rebuild_yhat(op_dir):
    params = np.load(os.path.join(op_dir, "params.npy"))
    quant_step = np.split(params, 3, axis=1)[0]
    q_dec = np.maximum(quant_step, np.float32(0.5)).astype(np.float32)

    masks = G.make_masks(256, 16, 16)
    mb = [m.astype(bool) for m in masks]
    shape = (1, 256, 16, 16)
    yh = np.zeros(shape, dtype=np.float32)
    for k in range(4):
        sym = np.fromfile(os.path.join(op_dir, "p%d_sym.i32" % k), dtype=np.int32)
        mraw = np.fromfile(os.path.join(op_dir, "p%d_means_raw.f32" % k),
                           dtype=np.float32).reshape(shape)
        mn = compact(mraw, mb[k]).astype(np.float32)
        comb = (mn + sym.astype(np.float32)).astype(np.float32)
        if comb.size != int(np.broadcast_to(mb[k], shape).sum()):
            raise RuntimeError("相位 %d 操作数个数 %d 与掩码 %d 不符"
                               % (k, comb.size, int(np.broadcast_to(mb[k], shape).sum())))
        yh = (yh + scatter(comb, mb[k], shape)).astype(np.float32)
    return (yh * q_dec).astype(np.float32)


def stats_of(a):
    v = a.reshape(-1)
    qs = [0.1, 1, 5, 25, 50, 75, 95, 99, 99.9]
    pct = np.percentile(v, qs)
    return {
        "n": int(v.size), "min": float(v.min()), "max": float(v.max()),
        "absmax": float(np.abs(v).max()), "mean": float(v.mean()), "std": float(v.std()),
        "pct": {float(k): float(x) for k, x in zip(qs, pct)},
        "gt3": float((np.abs(v) > 3.0).mean()) * 100.0,
        "gt8": float((np.abs(v) > 8.0).mean()) * 100.0,
        "gt16": float((np.abs(v) > 16.0).mean()) * 100.0,
    }


def report(name, s):
    print("   【y_hat】%-10s min=%.4f  max=%.4f  |max|=%.4f  mean=%.4f  std=%.4f"
          % (name, s["min"], s["max"], s["absmax"], s["mean"], s["std"]))
    print("            分位: " + "  ".join("%g%%=%.3f" % (k, v) for k, v in s["pct"].items()))
    print("            超 ±3 比例=%.4f%%   超 ±8=%.4f%%   超 ±16=%.4f%%"
          % (s["gt3"], s["gt8"], s["gt16"]))
    _rows.append((name, s))


# ---------------------------------------------------------------- 挂钩
_orig_cpu = glc_rsd_cpu.pl_encode_cpu


def pl_encode_hook(op_dir, rbase=None, chunk=None, reg=None):
    s = stats_of(rebuild_yhat(op_dir))
    report(_cur["name"], s)
    sys.stdout.flush()
    return _orig_cpu(op_dir, rbase, chunk, reg)


def _run_npu(key, cwd):
    global _engine
    if _engine is None:
        t = time.time()
        print("### [常驻引擎] 载入 5 个子图…")
        sys.stdout.flush()
        _engine = glc_rsd.Engine(G.MODELS)
        print("### [常驻引擎] 就绪：%.3f s" % (time.time() - t))
        sys.stdout.flush()
    return _engine.run(key, cwd)


def main():
    applied = glc_rsd_cpu.patch(G)
    glc_rsd_cpu.pl_encode_cpu = pl_encode_hook
    G.pl_encode = pl_encode_hook
    G.run_npu = _run_npu
    print("### [补丁] " + " / ".join(applied))

    jobs = []
    for a in sys.argv[1:]:
        n, p = (a.split("=", 1) if "=" in a
                else (os.path.splitext(os.path.basename(a))[0], a))
        jobs.append((n, p))
    if not jobs:
        print("用法: glc_yh_stats.py p1=/root/glc/inputs_photo/p1.ftmp ...")
        sys.exit(2)

    print("=" * 74)
    print("### 统计 %d 张的 y_hat（送进 S4 的输入）" % len(jobs))
    print("=" * 74)
    for n, p in jobs:
        if not os.path.exists(p):
            print("!! 缺输入 %s" % p)
            continue
        _cur["name"] = n
        shutil.copyfile(p, IN0)
        sys.argv = ["glc_board_full.py", "--sample", "0"]
        t0 = time.time()
        try:
            G.main()
        except Exception as e:
            import traceback
            traceback.print_exc()
            print("!! %s 失败: %s" % (n, e))
        md5 = hashlib.md5(open(PLGLC, "rb").read()).hexdigest() if os.path.exists(PLGLC) else "?"
        print("   -> %s 墙钟 %.3f s  容器 md5=%s" % (n, time.time() - t0, md5))
        sys.stdout.flush()

    # 写 TSV
    with open(OUTCSV, "w") as f:
        f.write("name\tmin\tmax\tabsmax\tmean\tstd\tp0.1\tp1\tp99\tp99.9\tgt3%\tgt8%\tgt16%\n")
        for name, s in _rows:
            f.write("%s\t%.5f\t%.5f\t%.5f\t%.5f\t%.5f\t%.5f\t%.5f\t%.5f\t%.5f\t%.4f\t%.4f\t%.4f\n"
                    % (name, s["min"], s["max"], s["absmax"], s["mean"], s["std"],
                       s["pct"][0.1], s["pct"][1.0], s["pct"][99.0], s["pct"][99.9],
                       s["gt3"], s["gt8"], s["gt16"]))
    print("=" * 74)
    print("### 汇总（y_hat）")
    print("   %-8s %9s %9s %9s %9s %9s" % ("图", "min", "max", "|max|", "std", "超±3%"))
    for name, s in _rows:
        print("   %-8s %9.4f %9.4f %9.4f %9.4f %8.4f%%"
              % (name, s["min"], s["max"], s["absmax"], s["std"], s["gt3"]))
    print("   已写 %s" % OUTCSV)
    print("YH_STATS_DONE")


if __name__ == "__main__":
    main()
