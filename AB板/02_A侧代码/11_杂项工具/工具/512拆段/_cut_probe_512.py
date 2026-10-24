# -*- coding: utf-8 -*-
"""列出 512 s4 ONNX 里 H<=128 的候选切点（边界张量要小，才能进 1 GB PS 内存）。"""
import onnx
import onnx.shape_inference as si

P = r'E:\fudanwei\工作区\onnx\c1_512\s4_gs_generator.onnx'
m = onnx.load(P)
m2 = si.infer_shapes(m)
vi = {}
for v in list(m2.graph.value_info) + list(m2.graph.output) + list(m2.graph.input):
    try:
        vi[v.name] = [d.dim_value for d in v.type.tensor_type.shape.dim]
    except Exception:
        pass

rows = []
for i, n in enumerate(m.graph.node):
    for o in n.output:
        s = vi.get(o)
        if s and len(s) == 4 and s[1] not in (0, None) and s[2] not in (0, None):
            rows.append((i, n.op_type, o, s))

print('nodes=%d  4D outputs=%d' % (len(m.graph.node), len(rows)))
lo = [r for r in rows if r[3][2] <= 128 and r[3][1] >= 16]
print('candidates (H<=128, C>=16): %d' % len(lo))
step = max(1, len(lo) // 45)
for r in lo[::step]:
    i, op, name, s = r
    nbytes = s[0] * s[1] * s[2] * s[3] * 4
    if nbytes > 2 * 1024 * 1024:
        print('%4d %-14s %-30s %-20s %8.2f MB' % (i, op, name[:30], str(s), nbytes / 1048576.0))
