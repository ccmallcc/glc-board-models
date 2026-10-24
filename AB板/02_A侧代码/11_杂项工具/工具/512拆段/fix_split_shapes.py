# -*- coding: utf-8 -*-
r"""把切出来的两段 ONNX 的输入/输出维度写死成真实值。

为什么必须做：extract_model 从 value_info 里抄来的 shape 带着 **batch=0**
（例如 `/generator/blocks.14/Resize_output_0 [0,512,128,128]`），
icraft-parse 会拿它跟 `--inputs` 比对，然后报
`input_dim in toml is not same with model` + `ShapeInfer Error: Got invalid dimensions`。
不是"参数给错"，是 ONNX 里那张卡片的维度就是 0。
"""
import onnx
import numpy as np

SPLIT = r'E:\fudanwei\工作区\split512'
JOBS = [
    (r's4_512_a.onnx', 'y_hat', (1, 256, 32, 32),
     '/generator/blocks.14/Resize_output_0', (1, 256, 128, 128)),
    (r's4_512_b.onnx', '/generator/blocks.14/Resize_output_0', (1, 256, 128, 128),
     'x_hat', (1, 3, 512, 512)),
]


def set_shape(vi, shape):
    tt = vi.type.tensor_type
    tt.shape.ClearField('dim')
    for d in shape:
        dim = tt.shape.dim.add()
        dim.dim_value = int(d)


def fix(fn):
    p = SPLIT + '\\' + fn
    m = onnx.load(p)
    jobs = [j for j in JOBS if j[0] == fn][0]
    _, in_name, in_shape, out_name, out_shape = jobs
    hit_in = hit_out = False
    for v in m.graph.input:
        if v.name == in_name:
            set_shape(v, in_shape); hit_in = True
    for v in m.graph.output:
        if v.name == out_name:
            set_shape(v, out_shape); hit_out = True
    # value_info 里同名的也一起改（否则 parser 可能仍读旧值）
    for v in m.graph.value_info:
        if v.name == in_name:
            set_shape(v, in_shape)
        if v.name == out_name:
            set_shape(v, out_shape)
    onnx.save(m, p)
    print('%s  in=%s%s out=%s%s  %.1f MB'
          % (fn, in_name, '' if hit_in else '(未命中!)',
             out_name, '' if hit_out else '(未命中!)',
             len(open(p, 'rb').read()) / 1048576.0))


def main():
    for j in JOBS:
        fix(j[0])
    # 自检：两段连着跑一遍，必须与全模型逐位相同
    import onnxruntime as ort
    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    a = ort.InferenceSession(SPLIT + r'\s4_512_a.onnx', so, providers=['CPUExecutionProvider'])
    b = ort.InferenceSession(SPLIT + r'\s4_512_b.onnx', so, providers=['CPUExecutionProvider'])
    full = ort.InferenceSession(r'E:\fudanwei\工作区\onnx\c1_512\s4_gs_generator.onnx', so,
                                providers=['CPUExecutionProvider'])
    cal = r'E:\fudanwei\工作区\calibref_512\calib\s4_gs_generator\00.ftmp'
    x = np.fromfile(cal, dtype=np.float32).reshape(1, 32, 32, 256).transpose(0, 3, 1, 2).copy()
    ref = full.run(None, {full.get_inputs()[0].name: x})[0]
    mid = a.run(None, {a.get_inputs()[0].name: x})[0]
    got = b.run(None, {b.get_inputs()[0].name: mid})[0]
    print('NUMEQ max|full-(b.a)| = %.3e  in_a=%s in_b=%s'
          % (float(np.max(np.abs(ref - got))), a.get_inputs()[0].name, b.get_inputs()[0].name))


if __name__ == '__main__':
    main()
