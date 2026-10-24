# -*- coding: utf-8 -*-
"""决定性检查：ONNX 到底是【静态形状】还是【动态形状】？

对比 onnx/c1_simple（size=256）与 onnx/c1_512（size=512）：
  ① graph.input 的维度是 dim_value（写死数字）还是 dim_param（符号名）？
  ② graph.output 同样
  ③ 图里有没有 Shape / Slice / Gather 这类"运行时读形状"的算子？
     —— 有 ⇒ 图是形状动态的；没有 ⇒ 形状被折叠成常量

这决定了 icraft 那次 "input_dim in toml is not same with model" 到底是什么意思。
"""
import os
import sys

import onnx

PAIRS = [
    (r'E:\fudanwei\工作区\onnx\c1_simple', 256),
    (r'E:\fudanwei\工作区\onnx\c1_512', 512),
]
NAMES = ['s1_encoder_ga_hyper', 's2_hyperdec_fusion', 's3_phase1', 's4_gs_generator']
DYN_OPS = ('Shape', 'Slice', 'Gather', 'Unsqueeze', 'Concat', 'Resize', 'ConstantOfShape')


def show_dim(d):
    if d.HasField('dim_value'):
        return str(d.dim_value)
    if d.HasField('dim_param'):
        return "'%s'" % d.dim_param
    return '?'


for d, size in PAIRS:
    print('=' * 78)
    print('目录 %s   （导出时 --size %d）' % (d, size))
    print('=' * 78)
    if not os.path.isdir(d):
        print('  （不存在）')
        continue
    for n in NAMES:
        p = os.path.join(d, n + '.onnx')
        if not os.path.exists(p):
            print('  %-22s 缺' % n)
            continue
        m = onnx.load(p, load_external_data=False)
        g = m.graph
        ins = ['%s:[%s]' % (i.name, ','.join(show_dim(x) for x in i.type.tensor_type.shape.dim))
               for i in g.input]
        outs = ['%s:[%s]' % (o.name, ','.join(show_dim(x) for x in o.type.tensor_type.shape.dim))
                for o in g.output]
        cnt = {}
        for node in g.node:
            cnt[node.op_type] = cnt.get(node.op_type, 0) + 1
        dyn = {k: cnt.get(k, 0) for k in DYN_OPS if cnt.get(k, 0)}
        ndyn = sum(dyn.values())
        print('  %-22s' % n)
        print('      输入 %s' % '; '.join(ins))
        print('      输出 %s' % '; '.join(outs))
        print('      算子总数 %d ；其中"动态形状类" %d 个  %s' % (len(g.node), ndyn, dyn if dyn else ''))
        # 判断静态/动态
        alldim = []
        for v in list(g.input) + list(g.output):
            for x in v.type.tensor_type.shape.dim:
                alldim.append(show_dim(x))
        has_sym = any(s.startswith("'") for s in alldim)
        print('      => 输入输出维度: %s' % ('**含符号维度（动态）**' if has_sym else '全是具体数字（静态）'))
        print('      => 图内是否用 Shape/Slice 运行时读形状: %s' % ('**是**' if ndyn else '否'))
        print()
print('ONNX_SHAPE_CHECK_DONE')
