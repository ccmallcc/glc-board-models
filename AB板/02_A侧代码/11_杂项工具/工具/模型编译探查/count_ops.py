# -*- coding: utf-8 -*-
"""逐阶段统计 s4 的算子类型：ONNX源 → parsed → optimized → quantized → adapted → ZG

用法：python count_ops.py            （必须从非 工作区 的目录运行，否则 工作区/onnx 会遮蔽真 onnx 包）
"""
import collections
import json
import os
import sys

BASE = r"E:\fudanwei\工作区"
FILES = [
    ("ONNX源",       BASE + r"\onnx\c1_simple\s4_gs_generator.onnx"),
    ("parsed",       BASE + r"\onnx\c1_simple\run\jr_s4_gs_generator\s4_gs_generator_parsed.json"),
    ("optimized",    BASE + r"\compile2\s4_int8\s4_gs_generator_optimized.json"),
    ("quantized",    BASE + r"\compile2\s4_int8\s4_gs_generator_quantized.json"),
    ("adapted",      BASE + r"\compile2\s4_int8\s4_gs_generator_adapted.json"),
    ("ZG(最终)",     BASE + r"\compile2\s4_int8\gen\s4_gs_generator_ZG.json"),
]
WATCH = ["Transpose", "Reshape", "Conv", "Conv2d", "Add", "Mul", "Multiply",
         "MatMul", "Matmul", "Softmax", "Upsample", "Resize", "Slice", "Concat",
         "Gemm", "InstanceNorm", "InstanceNorm2d", "SiLU", "Relu", "ReLU", "HardOp"]


def tk_of(o):
    if not isinstance(o, dict):
        return "?"
    for k in ("op_type", "type", "type_key", "opType"):
        if k in o:
            return str(o[k]).split("::")[-1]
    tk = str(o.get("_type_key", "?"))
    nm = str(o.get("name", "?"))
    # 名字形如 Transpose_123 / Reshape_45 —— 取前缀，去掉尾部编号
    pre = nm.rsplit("_", 1)[0] if "_" in nm else nm
    return "%s|%s" % (tk.split("::")[-1], pre)


def count_onnx(p):
    import onnx
    g = onnx.load(p)
    return len(g.graph.node), collections.Counter(n.op_type for n in g.graph.node)


def count_json(p):
    d = json.load(open(p, encoding="utf-8"))
    ops = d.get("ops") if isinstance(d, dict) else None
    if ops is None:
        return None, None, ("顶层键: " + ",".join(list(d)[:12]) if isinstance(d, dict) else type(d).__name__)
    return len(ops), collections.Counter(tk_of(o) for o in ops), ""


def main():
    print("%-11s %8s  %s" % ("阶段", "算子数", "关注的算子（个数）"))
    print("-" * 100)
    for name, p in FILES:
        if not os.path.exists(p):
            print("%-11s %8s  MISSING %s" % (name, "-", p))
            continue
        if p.endswith(".onnx"):
            try:
                n, c = count_onnx(p)
            except Exception as e:
                print("%-11s %8s  跳过(%s)" % (name, "-", str(e)[:50]))
                continue
            note = ""
        else:
            n, c, note = count_json(p)
            if n is None:
                print("%-11s %8s  %s" % (name, "-", note))
                continue
        w = "  ".join("%s=%d" % (k, c[k]) for k in WATCH if c.get(k))
        print("%-11s %8d  %s" % (name, n, w))
        top = "  ".join("%s=%d" % (k, v) for k, v in c.most_common(14))
        print("%-11s %8s  → %s" % ("", "", top))
    print("-" * 100)


if __name__ == "__main__":
    main()
