#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""poc_session2.py —— 验证常驻 Session（修正取数）

上一版报错：
    Check failed: (self.data().ptype() != PtrType::ADDR) is false
    The Tensor's memchunk is of ADDR type, can't be converted to buffer!
⇒ **输出 tensor 落在设备内存（ADDR 类型），不能直接 np.array()**，
   要用 Tensor.dump(流, "SFB") 或 Tensor.read(缓冲, off, n) 取回。
   （官方 dumpOutputFtmp 用的就是 dump。）

本脚本：Session forward 一次 S2，用 dump/read 两种方式取回输出，并与 icraft-run 的
        ftmpSFB/184.ftmp **逐字节对拍**。
"""
import io
import os
import sys
import time

import numpy as np

from icraft import xir, xrt
from icraft import host_backend

from icraft.zg330backend import ZG330Backend, OcmOpt

M = "/root/glc/models"
DEV_URL = os.environ.get("POC_DEV", "axi://zg330aiu?npu=0x40000000&dma=0x80000000")
TAG = os.environ.get("POC_TAG", "s2_hyperdec_fusion")
VID = int(os.environ.get("POC_VID", "184"))
IN_FTMP = os.environ.get("POC_IN", "in0.ftmp")
OUT_NP = os.environ.get("POC_OUT", "/tmp/poc_s2_out.npy")
REF = os.environ.get("POC_REF", "")


def step(msg, t0):
    print("  %-30s %8.3f s" % (msg, time.time() - t0))
    return time.time()


def main():
    print("=== POC2: 常驻 Session 跑 %s (v_id=%d) ===" % (TAG, VID))
    t = time.time()
    net = xir.Network.CreateFromJsonFile("%s/%s_ZG.json" % (M, TAG))
    t = step("1 CreateFromJsonFile", t)
    net.lazyLoadParamsFromFile("%s/%s_ZG.raw" % (M, TAG))
    t = step("2 lazyLoadParamsFromFile", t)

    nv = net.view(0).setOutputsOrderByValueIds([VID])
    t = step("3 view + setOutputs", t)

    dev = xrt.Device.Open(DEV_URL)
    t = step("4 Device.Open", t)

    sess = xrt.Session.Create([ZG330Backend, host_backend.HostBackend], nv,
                              [dev, xrt.HostDevice.Default()])
    try:
        ZG330Backend(sess.backends[0]).ocmOptimize(OcmOpt.OPTION1)
    except Exception as e:
        print("  (ocmOptimize 跳过: %s)" % e)
    t = step("5 Session.Create + ocm", t)

    sess.enableTimeProfile(True)
    sess.apply()
    t = step("6 session.apply()  ★部署", t)

    arr = np.fromfile(IN_FTMP, dtype=np.float32)
    iv = net.ops[0].outputs[0] if "InputNode" in net.ops[0].typeKey() else net.ops[0].inputs[0]
    tt = iv.tensorType()
    shape = list(tt.shape)
    if int(np.prod(shape)) != arr.size:
        print("  !! 形状 %s 乘积 %d != 文件元素 %d" % (shape, int(np.prod(shape)), arr.size))
    arr = arr[:int(np.prod(shape))].reshape(shape).astype(np.float32)
    tt.setShape(list(arr.shape))
    tin = xrt.Tensor(arr, tt)
    t = step("7 构造输入 Tensor", t)

    t0 = time.time()
    out = sess.forward([tin])
    dt = time.time() - t0
    print("  8 session.forward()  %.4f s   返回 %d 个 tensor" % (dt, len(out)))

    o = out[0]
    try:
        print("     输出 dtype = %s" % o.dtype())
    except Exception as e:
        print("     (dtype 取不到: %s)" % e)
    try:
        print("     输出 memRegion = %s" % o.memRegion())
    except Exception as e:
        print("     (memRegion 取不到: %s)" % e)

    # --- 取数方式 A：dump 到 BytesIO（官方 dumpOutputFtmp 就是这么做的）---
    bio = io.BytesIO()
    o.dump(bio, "SFB")
    raw = bio.getvalue()
    print("     [A] dump(SFB) -> %d B" % len(raw))
    aA = np.frombuffer(raw, dtype=np.float32)
    print("         展平 %d 个 float32" % aA.size)
    np.save(OUT_NP, aA)
    print("         已存 %s" % OUT_NP)

    # --- 取数方式 B：read 到缓冲 ---
    aB = None
    try:
        shp = list(o.dtype().shape)
        n = int(np.prod(shp))
        buf = bytearray(n * 4)
        o.read(buf, 0, n * 4)
        aB = np.frombuffer(bytes(buf), dtype=np.float32)
        same = (aA.size == aB.size) and bool(np.array_equal(aA, aB))
        print("     [B] read() -> %d 个 float32, 与 dump 相同 = %s" % (aB.size, same))
    except Exception as e:
        print("     [B] read() 失败: %s" % e)

    try:
        print("     timeProfile totalTime = %.3f ms" % sess.totalTime())
    except Exception as e:
        print("     (totalTime 取不到: %s)" % e)

    # --- 对拍 ---
    if REF and os.path.exists(REF):
        b = np.fromfile(REF, dtype=np.float32)
        print("=== 对拍 vs icraft-run 的 %s ===" % REF)
        print("   icraft-run 参考 %d 个 float32" % b.size)
        print("   session dump    %d 个 float32" % aA.size)
        if aA.size == b.size:
            d = np.abs(aA - b)
            neq = int((aA != b).sum())
            print("   max|d| = %g   不同元素 = %d / %d   %s"
                  % (d.max(), neq, b.size, "逐字节一致 ✅" if neq == 0 else "有差异"))
        else:
            print("   !! 元素数不同，无法逐元素比")
    else:
        print("(未给 POC_REF，跳过对拍)")

    print("POC2_DONE")


if __name__ == "__main__":
    main()
