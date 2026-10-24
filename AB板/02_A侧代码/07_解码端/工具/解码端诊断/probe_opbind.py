#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""probe_opbind.py —— **逐个算子问后端**：你到底接不接？（这才是决定性的证据）

为什么要这么问：
  `icraft-run --log_time` 把算子打成 `Conv2d(H)`。我先前断定 `(H)` = Host 后端，
  但反证出现了 —— `--backends "Host"`（官方用法里明确合法、且是默认值）单独跑
  **失败**：
      Check failed: (is_bound) is false
      Op is NOT bound to any backend, op_id = 5030, type_key = icraft::xir::HardOpNode
  如果算子都在 Host 上跑，单给 Host 就该成功。它失败 ⇒ **(H) 不等于"Host 后端"**。
  （旁证：模型 JSON 里这些节点的 _type_key 正是 `icraft::xir::HardOpNode`，
    所以 `(H)` 很可能只是 **H**ardOp 的标记，跟后端无关。）

`xrt.pyi` 里有官方接口：
    Backend.getForwardFunc(op: xir.Operation) -> Callable | None
      —— 后端接不了这个算子就返回 None。这就是后端分派的判据。

本脚本对每个算子分别问 ZG330 后端和 Host 后端，统计谁能接。
"""
import collections
import os
import sys

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
    dev = xrt.Device.Open(DEV_URL)
    dev.reset(1)
    net = xir.Network.CreateFromJsonFile(base + ".json")
    net.lazyLoadParamsFromFile(base + ".raw")
    nv = net.view(0).setOutputsOrderByValueIds(vids)
    sess = xrt.Session.Create([ZG330Backend, host_backend.HostBackend], nv,
                              [dev, xrt.HostDevice.Default()])
    try:
        ZG330Backend(sess.backends[0]).ocmOptimize(OcmOpt.OPTION1)
    except Exception as e:
        print("  (ocmOptimize 跳过: %s)" % str(e)[:60])
    sess.enableTimeProfile(True)
    sess.apply()
    backends = list(sess.backends)
    print("模型 %s   共 %d 个 op" % (base, len(net.ops)))
    print("后端列表 %s  （数=%d）" % ([type(b).__name__ for b in backends], len(backends)))

    stat = collections.Counter()
    by_type = collections.defaultdict(collections.Counter)
    for op in net.ops:
        who = []
        for i, b in enumerate(backends):
            try:
                f = b.getForwardFunc(op)
            except Exception:
                f = None
            if f is not None:
                who.append(i)
        tk = str(getattr(op, "type_key", "?")).split("::")[-1]
        
        key_s = "+".join(str(i) for i in who) if who else "NONE"
        stat[key_s] += 1
        by_type[tk][key_s] += 1

    names = {0: "ZG330", 1: "Host"}
    print("\n=== 每个算子能被哪些后端接住 ===")
    for k, v in sorted(stat.items(), key=lambda x: -x[1]):
        lab = k if k == "NONE" else " & ".join(names.get(int(i), "?") for i in k.split("+"))
        print("  %-14s %5d 个  (%.1f%%)" % (lab, v, 100.0 * v / max(1, len(net.ops))))

    print("\n=== 按算子类型看（前 12 类）===")
    for tk, c in sorted(by_type.items(), key=lambda x: -sum(x[1].values()))[:12]:
        tot = sum(c.values())
        det = "  ".join("%s=%d" % (k, n) for k, n in c.most_common())
        print("  %-18s 共%4d   %s" % (tk, tot, det))

    zg = sum(v for k, v in stat.items() if "NONE" not in k and "0" in k.split("+"))
    ho = sum(v for k, v in stat.items() if "NONE" not in k and "1" in k.split("+"))
    no = stat.get("NONE", 0)
    print("\n★ 结论：能被 ZG330 接住 %d 个；能被 Host 接住 %d 个；谁也接不住 %d 个（共 %d）"
          % (zg, ho, no, len(net.ops)))
    if zg == 0:
        print("   ⇒ **ZG330 一个算子都接不住**，全部由 Host(CPU/MNN) 执行 ⇒ NPU 闲置。")
    elif ho == 0:
        print("   ⇒ **全部由 ZG330(NPU) 执行**，Host 只是摆设。")
    else:
        print("   ⇒ 两者分工：ZG330 接 %d 个，Host 接 %d 个。" % (zg, ho))
    print("PROBE_OPBIND_DONE")


if __name__ == "__main__":
    main()
