#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_io.py —— 查清每个子图的输入/输出到底怎么定义（为了正确组 forward 的入参）"""
import os
import sys
from collections import Counter

from icraft import xir

M = "/root/glc/models"
NAMES = {
    "s1": "s1_encoder_ga_hyper",
    "s2": "s2_hyperdec_fusion",
    "s3p1": "s3_phase1",
    "s3p2": "s3_phase2",
    "s3p3": "s3_phase3",
}


def shp(v):
    try:
        return list(v.tensorType().shape)
    except Exception as e:
        return "?%s" % e


def main():
    for key, name in NAMES.items():
        print("=" * 70)
        print("### %s  (%s)" % (key, name))
        net = xir.Network.CreateFromJsonFile("%s/%s_ZG.json" % (M, name))
        try:
            n = len(net.ops)
        except Exception as e:
            print("  !! len(net.ops) 失败: %s" % e)
            n = 0
        print("  len(net.ops) = %d" % n)

        # Network 上有没有 inputs()/outputs()
        for meth in ("inputs", "outputs"):
            try:
                f = getattr(net, meth)
                r = f()
                print("  net.%s() -> %d 个: %s" % (meth, len(r), [shp(v) for v in r]))
            except Exception as e:
                print("  net.%s() 不可用: %s" % (meth, e))

        tc = Counter()
        input_ops = []
        for i in range(n):
            op = net.ops[i]
            try:
                tk = op.typeKey()
            except Exception as e:
                tk = "?%s" % e
            tc[tk] += 1
            if "Input" in tk:
                outs = []
                try:
                    for o in op.outputs:
                        outs.append(shp(o))
                except Exception as e:
                    outs = "?%s" % e
                input_ops.append((i, tk, outs))
        print("  op 类型分布: %s" % dict(tc))
        print("  含 'Input' 的 op: %d 个" % len(input_ops))
        for i, tk, outs in input_ops:
            print("     idx=%-5d %-45s outputs=%s" % (i, tk, outs))

        # 打印每个 Input op 的 inputs/outputs 数量与 v_id
        for i, tk, outs in input_ops:
            op = net.ops[i]
            try:
                no = len(op.outputs)
            except Exception:
                no = -1
            try:
                ni = len(op.inputs)
            except Exception:
                ni = -1
            print("     idx=%-5d inputs=%d outputs=%d" % (i, ni, no))
        # 也看看最后的输出 op
        try:
            last = net.ops[n - 1]
            print("  最后一个 op: idx=%d typeKey=%s" % (n - 1, last.typeKey()))
        except Exception as e:
            print("  (取最后 op 失败: %s)" % e)
        print()
    print("PROBE_IO_DONE")


if __name__ == "__main__":
    main()
