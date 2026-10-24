# -*- coding: utf-8 -*-
r"""把 512 的 s4_gs_generator 切成两段（为了让每段的设备字节 < 4.29 GB）。

做法：
  1) 先做 shape 推断，算出「切在 node k 之后，有几条边跨段、共多少字节」；
  2) 在中点附近挑一个**只有 1 条跨段边、且这条边 <= 32 MB** 的 k（边界张量要过 PS 内存，1 GB）；
  3) 用 onnx.utils.extract_model 导出 segA / segB；
  4) 用 onnxruntime 验数值等价：full(x) vs segB(segA(x))，max|diff| 必须为 0。
     （同一张图切成两半、纯确定性算子，理应是逐位相同；不是 0 就说明切错了。）

用法：
  python c1_split_s4_512.py                # 只算切点 + 打印候选
  python c1_split_s4_512.py --apply        # 真的导出 + 验等价
  python c1_split_s4_512.py --apply --k 348
"""
import argparse
import os
import sys

import numpy as np
import onnx
import onnx.shape_inference as si
import onnx.utils

SRC = r'E:\fudanwei\工作区\onnx\c1_512\s4_gs_generator.onnx'
OUT = r'E:\fudanwei\工作区\split512'
IN_NAME = 'y_hat'
OUT_NAME = 'x_hat'


def shapes_of(m):
    vi = {}
    for v in list(m.graph.value_info) + list(m.graph.output) + list(m.graph.input):
        try:
            vi[v.name] = [d.dim_value for d in v.type.tensor_type.shape.dim]
        except Exception:
            pass
    return vi


def nbytes(s):
    if not s:
        return 0
    n = 4
    for d in s:
        n *= (d or 1)
    return n


def crossings(nodes, k, produced_by, consumed_after):
    """切在 nodes[k] 之后（segA = nodes[:k+1]）时，跨段的张量集合。"""
    return sorted(consumed_after)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--k', type=int, default=-1)
    a = ap.parse_args()

    m0 = onnx.load(SRC)
    m = si.infer_shapes(m0)
    vi = shapes_of(m)
    nodes = list(m.graph.node)
    N = len(nodes)

    producer = {}
    for i, n in enumerate(nodes):
        for o in n.output:
            producer[o] = i
    init = {t.name for t in m.graph.initializer}

    # 每个 k 的跨段边
    best = []
    for k in range(N - 1):
        after = set()
        for i in range(k + 1, N):
            for inp in nodes[i].input:
                if inp in init or inp == '':
                    continue
                p = producer.get(inp)
                if p is not None and p <= k:
                    after.add(inp)
        # 输出不能跨（终点的图输出必须留在 segB）
        if OUT_NAME in after:
            continue
        tot = sum(nbytes(vi.get(t)) for t in after)
        best.append((k, len(after), tot, sorted(after)))

    # 候选：1 条边、<=32MB、尽量靠近中点
    cand = [b for b in best if b[1] == 1 and b[2] <= 32 * 1024 * 1024]
    print('nodes=%d  候选(单边,<=32MB)=%d' % (N, len(cand)))
    if not cand:
        print('没有单边候选，退一步看 2 条边的：')
        cand = [b for b in best if b[1] <= 2 and b[2] <= 32 * 1024 * 1024]
    cand.sort(key=lambda b: abs(b[0] - N * 0.5))
    for k, ne, tot, names in cand[:12]:
        print('  k=%-4d 跨段 %d 条  %8.2f MB   中点差 %+d   %s'
              % (k, ne, tot / 1048576.0, k - N // 2, names[:2]))

    if not a.apply:
        return 0

    k = a.k if a.k >= 0 else cand[0][0]
    ne, tot, names = [(x[1], x[2], x[3]) for x in cand if x[0] == k][0] \
        if any(x[0] == k for x in cand) else (0, 0, [])
    if not names:
        # 允许用户指定任意 k：重算一次
        after = set()
        for i in range(k + 1, N):
            for inp in nodes[i].input:
                if inp in init or inp == '':
                    continue
                p = producer.get(inp)
                if p is not None and p <= k:
                    after.add(inp)
        names = sorted(after)
    print('\n选定 k=%d，跨段张量：%s' % (k, names))

    os.makedirs(OUT, exist_ok=True)
    inf = os.path.join(OUT, 's4_512_full_inferred.onnx')
    onnx.save(m, inf)
    a_p = os.path.join(OUT, 's4_512_a.onnx')
    b_p = os.path.join(OUT, 's4_512_b.onnx')
    onnx.utils.extract_model(inf, a_p, [IN_NAME], names)
    onnx.utils.extract_model(inf, b_p, names, [OUT_NAME])
    print('导出 %s (%.1f MB) / %s (%.1f MB)'
          % (os.path.basename(a_p), os.path.getsize(a_p) / 1048576.0,
             os.path.basename(b_p), os.path.getsize(b_p) / 1048576.0))

    # ---- 数值等价 ----
    import onnxruntime as ort
    # ★ 必须用**真实 latent**（标定集里的 00.ftmp），不能用随机张量：
    #   本轮实测随机 y_hat 会让生成器输出 NaN（两次都是 nan），那种输入下"等价"没意义。
    CAL = 'E:/fudanwei/工作区/calibref_512/calib/s4_gs_generator/00.ftmp'
    x = np.fromfile(CAL, dtype=np.float32).reshape(1, 32, 32, 256).transpose(0, 3, 1, 2).copy()
    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    full = ort.InferenceSession(SRC, so, providers=['CPUExecutionProvider'])
    ref = full.run(None, {IN_NAME: x})[0]
    sa = ort.InferenceSession(a_p, so, providers=['CPUExecutionProvider'])
    sb = ort.InferenceSession(b_p, so, providers=['CPUExecutionProvider'])
    mid = sa.run(None, {IN_NAME: x})[0]
    got = sb.run(None, {names[0] if len(names) == 1 else names[0]: mid})[0] \
        if len(names) == 1 else sb.run(names, {'mid': mid})[0]
    # segB 的输入名就是跨段张量名；用 ";" 之外的通用写法：
    if got is None:
        raise SystemExit('segB 前向失败')
    d = float(np.max(np.abs(ref - got)))
    print('NUMEQ max|full-(segB.segA)| = %.3e   shape %s vs %s'
          % (d, ref.shape, got.shape))
    np.save(os.path.join(OUT, 'ref_xhat_512.npy'), ref)
    np.save(os.path.join(OUT, 'mid_512.npy'), mid)
    return 0 if d == 0.0 else 1


if __name__ == '__main__':
    sys.exit(main())
