#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""probe_which_backend.py —— 到底是谁在算：ZG330(NPU) 还是 Host(CPU/MNN)？

背景：`icraft-run --log_time` 把每个算子打成 `Conv2d(H)`，看台上所有算子都是 (H)。
但 `(H)` 是 opType 字符串**自带的后缀**（`libicraft_xrt.so` 里的格式串是
`opType: {:<10}`，括号不是单独字段），所以不能只凭它下结论。
B 侧看到的是 154 (H) / 0 (Z)，我们这边是 1114 (H) / 0 (Z)、s1 是 827 (H) / 0 (Z)。

已确认的旁证：`libicraft_hostbackend.so` 里全是 **MNN** 的符号
（`_ZN3MNN...OpType...`）⇒ Host 后端 = 阿里 MNN，纯 CPU 推理引擎。

本脚本用官方 Python API 分别建三种 Session，看**各自能不能 apply 成功**：
    ZG330 only  -> 只用 NPU 后端
    Host only   -> 只用 MNN(CPU)
    ZG330+Host  -> 实际用的这种（ZG330 优先，接不了才落 Host）

用法：python3 probe_which_backend.py [s1|s4_int8]
"""
import os
import sys
import time

from icraft import host_backend, xir, xrt
from icraft.zg330backend import OcmOpt, ZG330Backend

DEV_URL = "axi://zg330aiu?npu=0x40000000&dma=0x80000000"
CAND = {
    "s1":      ("/root/glc/models/s1_encoder_ga_hyper_ZG", [3310, 3314]),
    "s4_int8": ("/root/glc/models/s4_int8/s4_gs_generator_ZG", [4107]),
}


def main():
    key = sys.argv[1] if len(sys.argv) > 1 else "s1"
    base, vids = CAND[key]
    print("模型 %s   输出 v_id=%s" % (base, vids))

    dev = xrt.Device.Open(DEV_URL)
    dev.reset(1)
    net = xir.Network.CreateFromJsonFile(base + ".json")
    net.lazyLoadParamsFromFile(base + ".raw")
    nv = net.view(0).setOutputsOrderByValueIds(vids)
    print("  网络共 %d 个 op" % len(net.ops))

    cases = (
        ("ZG330 only（只用 NPU）", [ZG330Backend], [dev]),
        ("Host only（只用 MNN/CPU）", [host_backend.HostBackend], [xrt.HostDevice.Default()]),
        ("ZG330+Host（实际用的）", [ZG330Backend, host_backend.HostBackend],
         [dev, xrt.HostDevice.Default()]),
    )
    for name, backs, devs in cases:
        t = time.time()
        try:
            s = xrt.Session.Create(backs, nv, devs)
            try:
                if backs[0] is ZG330Backend:
                    ZG330Backend(s.backends[0]).ocmOptimize(OcmOpt.OPTION1)
            except Exception as e:
                print("      (ocmOptimize 跳过: %s)" % str(e)[:60])
            s.enableTimeProfile(True)
            s.apply()
            print("  %-26s apply 成功    %.2f s   ★ 这个后端接得住" % (name, time.time() - t))
            del s
        except Exception as e:
            msg = str(e).replace("\n", " ")[:200]
            print("  %-26s **失败**      %.2f s   %s" % (name, time.time() - t, msg))
    print("\n结论：只有 apply 成功的那些后端才能执行这些算子。")
    print("      若 'ZG330 only' 失败而 'Host only' 成功 ⇒ **算子实际跑在 CPU(MNN) 上，NPU 闲置**。")
    print("PROBE_BACKEND_DONE")


if __name__ == "__main__":
    main()
