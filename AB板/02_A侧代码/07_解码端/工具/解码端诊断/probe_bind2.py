#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""probe_bind2.py —— 把「会话级」与「逐算子级」两个判定并排放在一起跑一次。

背景：B 侧观察到
    [A] Session.Create([ZG330Backend], ...)          ⇒ apply 抛异常
    [B] Session.Create([ZG330Backend, HostBackend])  ⇒ apply 成功
并据此下结论「**ZG330 一个算子都绑不上**，只有 Host 兜底才能跑」。

问题在于：**会话级 apply 失败 ≠ 没有任何算子能绑上**。
框架要求会话内**全部**算子都被绑住；只要有 1 个绑不上，apply 就抛异常。

本脚本一次跑清三件事：
  [A] 只给 ZG330 建会话 —— 失败时打出**抛异常的原文**（里面自带 `op_id = N`）
  [B] 逐算子问 `Backend.getForwardFunc(op)` —— ZG330 到底接住多少个、哪些接不住
  [C] 只给 Host 建会话 —— 同样打原文
判据：若 [A]/[C] 报出的 op_id 正好是 [B] 名单里的算子，而其余绝大多数算子
      ZG330 都接得住 ⇒ 「一个算子都绑不上」被否证。
"""
import collections
import os
import sys
import traceback

from icraft import host_backend, xir, xrt
from icraft.zg330backend import OcmOpt, ZG330Backend

DEV_URL = "axi://zg330aiu?npu=0x40000000&dma=0x80000000"
MODELS = {
    "s1": ("/root/glc/models/s1_encoder_ga_hyper_ZG", [3310, 3314]),
    "s4": ("/root/glc/models/s4_int8/s4_gs_generator_ZG", [4107]),
    "s4bf16": ("/root/glc/models/s4_bf16/s4_gs_generator_ZG", None),
    "s2": ("/root/glc/models/s2_hyperdec_fusion_ZG", None),
    "s3": ("/root/glc/models/s3_phase1_ZG", None),
}


def first_line(e):
    """异常原文：优先抓 `is_bound` / `Check failed` 那一行（自带 op_id）。"""
    t = "".join(traceback.format_exception_only(type(e), e)).strip()
    lines = [ln.strip() for ln in t.replace("\r", "\n").split("\n") if ln.strip()]
    hits = [ln for ln in lines
            if ("is_bound" in ln or "Check failed" in ln or "op_id" in ln
                or "not bound" in ln or "InternalError" in ln)]
    if hits:
        return " || ".join(hits)[-500:]
    return " | ".join(lines)[-500:]


def load(base, vids):
    net = xir.Network.CreateFromJsonFile(base + ".json")
    net.lazyLoadParamsFromFile(base + ".raw")
    nv = None
    if vids:
        try:
            nv = net.view(0).setOutputsOrderByValueIds(vids)
        except Exception as e:
            print("  (setOutputsOrderByValueIds(%s) 失败: %s ⇒ 退回 net.view(0))"
                  % (vids, first_line(e)[:80]))
            nv = None
    if nv is None:
        nv = net.view(0)
    return net, nv


def try_session(label, backends, devs, nv, net):
    """建会话 → apply；返回 (ok, 异常原文)。"""
    print("\n--- [%s] 后端 = %s" % (label, [getattr(b, "__name__", str(b)) for b in backends]))
    try:
        sess = xrt.Session.Create(backends, nv, devs)
    except Exception as e:
        print("    Session.Create 就抛了: %s" % first_line(e))
        return False, first_line(e)
    try:
        sess.apply()
    except Exception as e:
        msg = first_line(e)
        print("    Create 成功，**apply 抛异常**：\n      %s" % msg)
        return False, msg
    print("    apply 成功")
    return True, ""


def per_op(net, backends, names):
    """逐个算子问每个后端接不接。"""
    stat = collections.Counter()
    by_type = collections.defaultdict(collections.Counter)
    no_zg, no_host = [], []
    ops = list(net.ops)
    for op in ops:
        who = []
        for i, b in enumerate(backends):
            try:
                f = b.getForwardFunc(op)
            except Exception:
                f = None
            if f is not None:
                who.append(i)
        k = "+".join(str(i) for i in who) if who else "NONE"
        stat[k] += 1
        tk = str(getattr(op, "type_key", "?")).split("::")[-1]
        by_type[tk][k] += 1
        try:
            oid = op.op_id
        except Exception:
            oid = "?"
        tv = str(getattr(op, "type_key", "?"))
        if 0 not in who:
            no_zg.append((oid, tv))
        if 1 not in who:
            no_host.append((oid, tv))
    n = max(1, len(ops))
    print("    op 总数 %d" % len(ops))
    for k, v in sorted(stat.items(), key=lambda x: -x[1]):
        lab = k if k == "NONE" else " & ".join(names[int(i)] for i in k.split("+"))
        print("      %-16s %5d 个 (%.2f%%)" % (lab, v, 100.0 * v / n))
    zg = sum(v for k, v in stat.items() if "NONE" not in k and "0" in k.split("+"))
    ho = sum(v for k, v in stat.items() if "NONE" not in k and "1" in k.split("+"))
    print("    ★ ZG330 能接 %d/%d = %.2f%%   Host 能接 %d/%d = %.2f%%   无人接 %d"
          % (zg, len(ops), 100.0 * zg / n, ho, len(ops), 100.0 * ho / n, stat.get("NONE", 0)))
    print("    ★ ZG330 接不住的（%d 个）: %s" % (len(no_zg), no_zg[:12]))
    print("    ★ Host  接不住的（%d 个）: %s" % (len(no_host), no_host[:12]))
    print("    --- 接不住 ZG330 的按类型 ---")
    c = collections.Counter(t for _, t in no_zg)
    for t, v in c.most_common(10):
        print("      %-40s %d" % (t.split("::")[-1], v))
    return no_zg, no_host


def main():
    key = sys.argv[1] if len(sys.argv) > 1 else "s4"
    base, vids = MODELS[key]
    print("模型 = %s.json" % base)
    print("=" * 78)

    dev = xrt.Device.Open(DEV_URL)
    print("Device.Open 成功：%s" % getattr(dev, "name", "?"))
    dev.reset(1)

    names = {0: "ZG330", 1: "Host"}

    # ---- [A] 只给 ZG330 ----
    net, nv = load(base, vids)
    okA, msgA = try_session("A 只给 ZG330", [ZG330Backend], [dev], nv, net)

    # ---- [C] 只给 Host ----
    net, nv = load(base, vids)
    okC, msgC = try_session("C 只给 Host", [host_backend.HostBackend],
                           [xrt.HostDevice.Default()], nv, net)

    # ---- [B] 两个都给 + 逐算子 ----
    net, nv = load(base, vids)
    try:
        sess = xrt.Session.Create([ZG330Backend, host_backend.HostBackend], nv,
                                  [dev, xrt.HostDevice.Default()])
        try:
            ZG330Backend(sess.backends[0]).ocmOptimize(OcmOpt.OPTION1)
        except Exception as e:
            print("  (ocmOptimize 跳过: %s)" % first_line(e)[:80])
        sess.enableTimeProfile(True)
        sess.apply()
        print("\n--- [B] ZG330 + Host : apply 成功")
        bks = list(sess.backends)
        print("    后端实例 = %s" % [type(b).__name__ for b in bks])
    except Exception as e:
        print("\n--- [B] ZG330 + Host : 也失败了: %s" % first_line(e))
        return 1

    no_zg, no_host = per_op(net, bks, names)

    print("\n" + "=" * 78)
    print("【判定】")
    print("  [A] 只给 ZG330 → %s" % ("成功" if okA else "失败"))
    print("  [C] 只给 Host  → %s" % ("成功" if okC else "失败"))
    print("  [B] ZG330 逐算子接住数 = %d / %d" % (len(list(net.ops)) - len(no_zg), len(list(net.ops))))
    if not okA and len(no_zg) > 0:
        print("  ⇒ [A] 失败是因为**这 %d 个**算子 ZG330 接不住，不是因为「一个都接不上」。" % len(no_zg))
    if not okC:
        print("  ⇒ [C] 失败是因为有 %d 个算子只有 ZG330 能接。" % len(no_host))
    print("PROBE_BIND2_DONE")


if __name__ == "__main__":
    main()
