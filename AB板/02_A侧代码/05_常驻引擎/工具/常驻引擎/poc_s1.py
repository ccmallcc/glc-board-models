#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""poc_s1.py —— 测 S1（157 MB，编码链路的大头）走常驻 Session 的一次性成本

目标：回答"值不值"。
  icraft-run 每跑一次 S1 要 6.66 s（其中 NPU 硬时间只有 346 ms）
  如果 Session 的一次性成本 ≈ 6 s，那么：
      常驻进程跑 N 张图 ≈ 一次性 + N × 0.35 s
      N=1 -> ~6.4 s（比 9.4 s 小赢）；N=7 -> ~8.5 s（比 66 s 快 7.8 倍）

只测 S1，不做胶水；输出与 icraft-run 的 ftmpSFB dump 对拍。
"""
import io
import os
import time

import numpy as np

from icraft import xir, xrt
from icraft import host_backend
from icraft.zg330backend import ZG330Backend, OcmOpt

M = "/root/glc/models"
TAG = "s1_encoder_ga_hyper"
VIDS = [3310, 3314]
DEV_URL = "axi://zg330aiu?npu=0x40000000&dma=0x80000000"
REFDIR = "/root/glc/run/s1/logs/s1_encoder_ga_hyper/ftmpSFB"


def step(msg, t0):
    print("  %-32s %8.3f s" % (msg, time.time() - t0))
    return time.time()


def mem():
    try:
        with open("/proc/self/status") as f:
            for ln in f:
                if ln.startswith("VmRSS"):
                    return ln.split()[1] + " kB"
    except Exception:
        pass
    return "?"


def main():
    print("=== POC-S1: 常驻 Session 跑 %s %s ===" % (TAG, VIDS))
    t = time.time()
    net = xir.Network.CreateFromJsonFile("%s/%s_ZG.json" % (M, TAG))
    t = step("1 CreateFromJsonFile (1.2MB json)", t)
    net.lazyLoadParamsFromFile("%s/%s_ZG.raw" % (M, TAG))
    t = step("2 lazyLoadParamsFromFile (157MB)", t)
    print("     RSS = %s" % mem())

    nv = net.view(0).setOutputsOrderByValueIds(VIDS)
    t = step("3 view + setOutputs", t)

    dev = xrt.Device.Open(DEV_URL)
    t = step("4 Device.Open", t)

    sess = xrt.Session.Create([ZG330Backend, host_backend.HostBackend], nv,
                              [dev, xrt.HostDevice.Default()])
    try:
        ZG330Backend(sess.backends[0]).ocmOptimize(OcmOpt.OPTION1)
    except Exception as e:
        print("     (ocmOptimize 跳过: %s)" % e)
    t = step("5 Session.Create", t)

    sess.enableTimeProfile(True)
    sess.apply()
    t = step("6 session.apply() ★部署", t)
    print("     RSS = %s" % mem())
    print("     >>> 一次性总成本到此为止 <<<")

    arr = np.fromfile("/root/glc/run/s1/in0.ftmp", dtype=np.float32)
    iv = net.ops[0].outputs[0] if "InputNode" in net.ops[0].typeKey() else net.ops[0].inputs[0]
    tt = iv.tensorType()
    shape = list(tt.shape)
    arr = arr[:int(np.prod(shape))].reshape(shape).astype(np.float32)
    tt.setShape(list(arr.shape))
    tin = xrt.Tensor(arr, tt)

    for k in range(1, 4):
        t0 = time.time()
        out = sess.forward([tin])
        dt = time.time() - t0
        print("  forward 第 %d 次  %.4f s   返回 %d 个 tensor" % (k, dt, len(out)))
        if k == 1:
            for i, o in enumerate(out):
                bio = io.BytesIO()
                o.dump(bio, "SFB")
                raw = bio.getvalue()
                a = np.frombuffer(raw, dtype=np.float32)
                print("     out[%d] v_id=%d dump=%d B (%d float32) shape=%s"
                      % (i, VIDS[i], len(raw), a.size, list(o.dtype().shape)))
                np.save("/tmp/poc_s1_out%d.npy" % i, a)
        try:
            dev.reset(1)
        except Exception:
            pass

    # 对拍
    print("=== 对拍 vs icraft-run 的 ftmpSFB ===")
    for i, v in enumerate(VIDS):
        ref = "%s/%d.ftmp" % (REFDIR, v)
        if not os.path.exists(ref):
            print("   v_id %d: 参考 %s 不存在，跳过" % (v, ref))
            continue
        a = np.load("/tmp/poc_s1_out%d.npy" % i)
        b = np.fromfile(ref, dtype=np.float32)
        if a.size == b.size:
            neq = int((a != b).sum())
            print("   v_id %-5d  session %d  float32  参考 %d  float32  max|d|=%.3g  不同=%d  %s"
                  % (v, a.size, b.size, np.abs(a - b).max(), neq,
                     "逐字节一致 ✅" if neq == 0 else "有差异"))
        else:
            print("   v_id %d 元素数不同: %d vs %d" % (v, a.size, b.size))
    print("POC_S1_DONE")


if __name__ == "__main__":
    main()
