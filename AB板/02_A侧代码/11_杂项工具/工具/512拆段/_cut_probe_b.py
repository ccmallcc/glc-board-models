# -*- coding: utf-8 -*-
"""在 segB 里再找切点：列单边跨段、边界 <=64 MB 的候选。"""
import onnx
import onnx.shape_inference as si

P = r'E:\fudanwei\工作区\split512\s4_512_b.onnx'
m = si.infer_shapes(onnx.load(P))
vi = {}
for v in list(m.graph.value_info) + list(m.graph.output) + list(m.graph.input):
    try:
        vi[v.name] = [d.dim_value for d in v.type.tensor_type.shape.dim]
    except Exception:
        pass

nodes = list(m.graph.node)
N = len(nodes)
print('segB nodes =', N)
prod = {}
for i, n in enumerate(nodes):
    for o in n.output:
        prod[o] = i

rows = []
for k in range(N - 1):
    after = set()
    for i in range(k + 1, N):
        for inp in nodes[i].input:
            p = prod.get(inp)
            if p is not None and p <= k and inp not in ('x_hat',):
                after.add(inp)
    if len(after) == 1:
        t = list(after)[0]
        s = vi.get(t)
        if s and len(s) == 4 and s[1] > 0:
            nb = s[1] * s[2] * s[3] * 4
            if nb <= 64 * 1024 * 1024:
                rows.append((k, t, s, nb / 1048576.0))

print('候选 %d 条（单边、边界<=64MB）：' % len(rows))
for k, t, s, mb in rows:
    print('  k=%-3d %-46s %-22s %6.1f MB' % (k, t[:46], str(s), mb))
