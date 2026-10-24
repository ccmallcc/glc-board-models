# -*- coding: utf-8 -*-
r"""seg_probe.py —— 量清楚「切段到底造了多少算子」，不靠编译。

要回答的问题（B 侧 §二.2 主张）：
    "整图 659 个算子，切成 5 段后合计 1055 个 HardOp（+60%）"

可疑点：674 个 ONNX 节点，切成 5 段却合计 1055 ⇒ 比整图还多 381。
而 `onnx.utils.extract_model` 是**从输出反向求传递闭包**的：只要跨越切点有分支，
它会把整条支路拉进来 ⇒ **相邻段会重叠、节点被重复计入**。

本脚本不用编译，直接量：
  1. 每段 extract_model 后**真实**包含哪些节点（按名字）
  2. 段与段之间**重复**了多少节点
  3. 段并集 vs 整图 —— 切段到底净增多少
"""
import os
import sys

import onnx
from onnx import TensorProto, shape_inference

SRC = r"E:\fudanwei\工作区\onnx\c1_simple\s4_gs_generator.onnx"
OUT = r"E:\fudanwei\_seg_probe"
DT = {TensorProto.FLOAT: 4, TensorProto.FLOAT16: 2, TensorProto.INT64: 8,
      TensorProto.INT32: 4, TensorProto.BOOL: 1, TensorProto.DOUBLE: 8}


def tensor_bytes_and_shape(t, sz):
    tt = t.type.tensor_type
    n = 1
    for d in tt.shape.dim:
        n *= (d.dim_value if d.HasField("dim_value") else 1)
    return n * DT.get(tt.elem_type, 4)


def build_sz(gr):
    sz = {}
    for t in list(gr.input) + list(gr.output) + list(gr.value_info):
        if t.type.HasField("tensor_type"):
            sz[t.name] = tensor_bytes_and_shape(t, sz)
    for init in gr.initializer:
        n = 1
        for d in init.dims:
            n *= d
        sz[init.name] = n * DT.get(init.data_type, 4)
    return sz


def load(p):
    m = shape_inference.infer_shapes(onnx.load(p))
    return m, m.graph, build_sz(m.graph)


def piece_nodes(gr, a, b):
    """模拟 extract_model(输入=node[a-1].output, 输出=node[b-1].output) 会保留哪些节点名。
    从 node[b-1] 的输出反向求祖先闭包；node[a-1].output 视为给定输入。"""
    prod = {}
    for i, n in enumerate(gr.node):
        for o in n.output:
            prod[o] = i
    stop = set(gr.node[a - 1].output) if a > 0 else set(t.name for t in gr.input)
    need, stack = set(), []
    for o in gr.node[b - 1].output:
        stack.append(o)
    while stack:
        t = stack.pop()
        if t in stop:
            continue
        i = prod.get(t)
        if i is None or i in need:
            continue
        need.add(i)
        for x in gr.node[i].input:
            stack.append(x)
    return need


def stats(gr, sz, idxs):
    tot = 0
    for i in idxs:
        for o in gr.node[i].output:
            tot += sz.get(o, 0)
    return len(idxs), tot


def main():
    os.makedirs(OUT, exist_ok=True)
    m, gr, sz = load(SRC)
    names = [n.name for n in gr.node]
    print("整图 ONNX: %d 节点, 张量合计 %.3f GB (icraft≈%.2f GB)"
          % (len(gr.node), sum(sz.get(o, 0) for n in gr.node for o in n.output) / 1e9,
             sum(sz.get(o, 0) for n in gr.node for o in n.output) / 1e9 * 5))

    # ---- 第一步：/dec 与 /generator 的天然边界 ----
    cut = next((i for i, n in enumerate(names) if n.startswith("/generator")), None)
    print("\n[1] /generator 首节点索引 = %s" % cut)
    if cut:
        a_piece = piece_nodes(gr, 0, cut)
        b_piece = piece_nodes(gr, cut, len(gr.node))
        na, ta = stats(gr, sz, a_piece)
        nb, tb = stats(gr, sz, b_piece)
        print("    s4a_dec  提取后 %3d 节点  %.3f GB (icraft≈%.2f GB)" % (na, ta / 1e9, ta / 1e9 * 5))
        print("    s4b_gen  提取后 %3d 节点  %.3f GB (icraft≈%.2f GB)" % (nb, tb / 1e9, tb / 1e9 * 5))
        print("    并集 %d ；两者之和 %d ；整图 %d ；**净增 %d**"
              % (len(a_piece | b_piece), na + nb, len(gr.node), na + nb - len(gr.node)))
        print("    /dec 区间 [0,%d) 里的节点，被 s4b_gen 拉回去的有 %d 个"
              % (cut, len([i for i in b_piece if i < cut])))

    # ---- 第二步：generator 再切 4 刀（复现 split_gen4 的默认切点）----
    if cut:
        M = len(gr.node)
        # s4b_gen 的节点索引 = 全局索引 - cut；extract_model 会先产出 s4b_gen.onnx，
        # 它的节点就是 b_piece。这里直接在全局图上按 generator 内序号切。
        gen = sorted(b_piece)
        for cuts in ([400, 479, 557],):
            bounds = [0] + cuts + [len(gen)]
            print("\n[2] generator 内切点 %s（generator 共 %d 节点）" % (cuts, len(gen)))
            pieces, tot_nodes = [], 0
            for k in range(len(bounds) - 1):
                lo, hi = bounds[k], bounds[k + 1]
                # 段输出 = generator 内第 hi-1 个节点的输出；段输入 = 第 lo-1 个的输出
                gi = gen[hi - 1]
                gj = gen[lo - 1] if lo > 0 else None
                # 在该段范围内做闭包（保持 extract_model 语义：从 s4b_gen 的输出反推）
                piece = set()
                prod = {}
                for i in b_piece:
                    for o in gr.node[i].output:
                        prod[o] = i
                stop = set(gr.node[gj].output) if gj is not None else set()
                # s4b_gen 是一个独立模型：其输出 = 全局 node[gen[-1]].output
                stack = list(gr.node[gi].output)
                while stack:
                    t = stack.pop()
                    if t in stop:
                        continue
                    i = prod.get(t)
                    if i is None or i in piece or i not in b_piece:
                        continue
                    piece.add(i)
                    for x in gr.node[i].input:
                        stack.append(x)
                n_, t_ = stats(gr, sz, piece)
                pieces.append(piece)
                tot_nodes += n_
                print("    b%d  闭包 %3d 节点  %.3f GB (icraft≈%.2f GB)"
                      % (k + 1, n_, t_ / 1e9, t_ / 1e9 * 5))
            union = set().union(*pieces) if pieces else set()
            print("    四段之和 %d ；并集 %d ；generator 本身 %d ；**净增 %d**"
                  % (tot_nodes, len(union), len(gen), tot_nodes - len(gen)))
            for i in range(len(pieces)):
                for j in range(i + 1, len(pieces)):
                    ov = pieces[i] & pieces[j]
                    if ov:
                        print("    ⚠ b%d ∩ b%d = %d 个节点被重复计入" % (i + 1, j + 1, len(ov)))
    print("\nSEG_PROBE_DONE")


if __name__ == "__main__":
    main()
