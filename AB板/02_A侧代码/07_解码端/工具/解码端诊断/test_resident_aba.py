#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""test_resident_aba.py —— 回答 B 侧那份警告：同一 Session 内交替喂不同输入，读数可靠吗？

B 侧实测（**他们的实现**）：
    输入 A,A,B,A,B  ⇒  结果 A,A,A,B,A      ← 第 3 次给 B 却读出 A 的结果 ✗
    还见到"写了一半"的脏值 3.1e12 / 2.7e17
    现象：forward() 返回设备侧张量、isReady() 恒 False、waitForReady() 第 2 发起 0.0001 s 就返回 True

本脚本用 **我们 glc_rsd.py 的读数方式**跑同一个实验，判定我们这条路是否可靠。
我们的读数方式（原文）：

    tt.setShape(list(a.shape))
    ten = xrt.Tensor(a, tt)            # ★ 每次新建（复用 + write() 会被框架当成"没变"而跳过重算）
    out = sess.forward([ten])          # ★ 同步调用，**没有单独的 wait/isReady**
    dev.reset(1)                       # ★ 每帧 forward 之后
    o.dump(bio, "SFB")                 # ★ 取输出

用法: python3 test_resident_aba.py [--noreset] [--seq AABAB] [--model s1]
"""
import argparse
import hashlib
import io
import os
import sys
import time

import numpy as np

from icraft import host_backend, xir, xrt
from icraft.zg330backend import OcmOpt, ZG330Backend

DEV_URL = "axi://zg330aiu?npu=0x40000000&dma=0x80000000"

MODELS = {
    "s1": ("/root/glc/models/s1_encoder_ga_hyper_ZG", [3310, 3314]),
    "s4": ("/root/glc/models/s4_int8/s4_gs_generator_ZG", [4107]),
}

# A / B / C 用三张**真实不同的照片**的编码器输入张量
IN = {
    "A": "/root/glc/inputs_photo/p1.ftmp",
    "B": "/root/glc/inputs_photo/p2.ftmp",
    "C": "/root/glc/inputs_photo/p3.ftmp",
}


def md5(b):
    return hashlib.md5(b).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="s1")
    ap.add_argument("--seq", default="AABAB")
    ap.add_argument("--noreset", action="store_true",
                    help="不调 device.reset(1) —— 用来验证 reset 是不是必需")
    a = ap.parse_args()

    base, vids = MODELS[a.model]
    seq = [c for c in a.seq if c in "ABC"]

    print("=" * 76)
    print("模型 %s   输入序列 %s   每帧 reset = %s"
          % (a.model, "".join(seq), not a.noreset))
    print("=" * 76)

    dev = xrt.Device.Open(DEV_URL)
    dev.reset(1)
    net = xir.Network.CreateFromJsonFile(base + ".json")
    net.lazyLoadParamsFromFile(base + ".raw")
    nv = net.view(0).setOutputsOrderByValueIds(vids)
    sess = xrt.Session.Create([ZG330Backend, host_backend.HostBackend], nv,
                              [dev, xrt.HostDevice.Default()])
    try:
        ZG330Backend(sess.backends[0]).ocmOptimize(OcmOpt.OPTION1)
    except Exception:
        pass
    sess.enableTimeProfile(True)
    sess.apply()
    print("常驻载入完成（%d 个输出 v_id: %s）" % (len(vids), vids))

    vals = list(net.inputs())
    tt = vals[0].tensorType()
    shp = list(tt.shape)
    n = int(np.prod(shp))

    data = {}
    for k, p in IN.items():
        v = np.fromfile(p, dtype=np.float32)
        if v.size != n:
            v = v[:n] if v.size >= n else np.concatenate([v, np.zeros(n - v.size, np.float32)])
        data[k] = np.ascontiguousarray(v.reshape(shp).astype(np.float32))
    print("输入 %s  每个 %d float（%.0f KB）" % (shp, n, n * 4 / 1024))

    # 先把每个输入的"基准输出"各跑一次（一次性，作为参照）
    print("\n--- 第 1 步：三个输入各跑一次，取参照 md5 ---")
    ref = {}
    for k in "ABC":
        tt.setShape(list(data[k].shape))
        ten = xrt.Tensor(data[k], tt)
        out = sess.forward([ten])
        bio = io.BytesIO()
        out[0].dump(bio, "SFB")
        ref[k] = md5(bio.getvalue())
        if not a.noreset:
            dev.reset(1)
        print("   输入 %s -> md5 %s" % (k, ref[k][:16]))

    # 第 2 步：按序列交替喂，看输出序列是否一一对应
    print("\n--- 第 2 步：同一 Session 内连续 forward，序列 %s ---" % "".join(seq))
    print("    %-4s %-6s %-18s %-9s %s" % ("#", "输入", "输出md5", "耗时s", "与参照"))
    seq_res = []
    for i, k in enumerate(seq):
        tt.setShape(list(data[k].shape))
        ten = xrt.Tensor(data[k], tt)          # ★ 每帧新建
        t0 = time.time()
        out = sess.forward([ten])              # ★ 同步
        el = time.time() - t0
        if not a.noreset:
            dev.reset(1)                       # ★ 每帧 reset
        bio = io.BytesIO()
        out[0].dump(bio, "SFB")                # ★ 取输出
        got = md5(bio.getvalue())
        seq_res.append((k, got, el))
        print("    %-4d %-6s %-18s %-9.3f %s"
              % (i + 1, k, got[:16], el, "OK" if got == ref[k] else "**不符**"))

    # ---- ★★ 判定：不能拿"同模式下算的参照值"比（参照值会被同一个 bug 一起污染，
    #      那样永远报 OK）。必须用**与参照无关**的判据：
    #        ① 同一个输入多次出现 ⇒ md5 必须完全相同
    #        ② 不同输入           ⇒ md5 必须**互不相同**（"两张不同容器必须出两个不同结果"）
    #        ③ 耗时不得异常小（跳过重算时实测会从 0.35 s 掉到 0.00x s）
    print("\n--- 判定（与参照无关的判据）---")
    by_in = {}
    for k, g, el in seq_res:
        by_in.setdefault(k, set()).add(g)
    stable = all(len(v) == 1 for v in by_in.values())
    reps = {k: sorted(v)[0] for k, v in by_in.items()}
    distinct = len(set(reps.values())) == len(reps)
    fast = [el for _, _, el in seq_res if el < 0.05]

    print("    ① 同输入重复出现 ⇒ 结果稳定      : %s  %s"
          % ("✅" if stable else "✗", {k: len(v) for k, v in by_in.items()}))
    print("    ② 不同输入       ⇒ 结果互不相同  : %s  %s"
          % ("✅" if distinct else "✗",
             " ".join("%s=%s" % (k, reps[k][:12]) for k in sorted(reps))))
    print("    ③ 耗时无异常小值                 : %s  %s"
          % ("✅" if not fast else "✗",
             "最小 %.3f s" % min(el for _, _, el in seq_res)))
    ok = stable and distinct and not fast
    print()
    if ok:
        print("  ✅ 结论：输入序列与输出序列**一一对应** ⇒ 这套读数方式是**可靠的**")
    else:
        print("  ✗ 结论：**读数不可靠** —— 生产链路上会有静默错误（结果看起来正常，其实是旧的）")

    # 第 3 步：有没有"写了一半"的脏值
    print("\n--- 第 3 步：脏值扫描（|值| 超过 1e6 视为可疑）---")
    tt.setShape(list(data["B"].shape))
    out = sess.forward([xrt.Tensor(data["B"], tt)])
    if not a.noreset:
        dev.reset(1)
    bio = io.BytesIO()
    out[0].dump(bio, "SFB")
    arr = np.frombuffer(bio.getvalue(), dtype=np.float32)
    big = int((np.abs(arr) > 1e6).sum())
    print("    %d 个元素，|x|>1e6 的 %d 个，max|x| = %.3g，mean = %.6f"
          % (arr.size, big, float(np.abs(arr).max()), float(arr.mean())))

    print("\nTEST_RESIDENT_ABA_DONE")


if __name__ == "__main__":
    main()
