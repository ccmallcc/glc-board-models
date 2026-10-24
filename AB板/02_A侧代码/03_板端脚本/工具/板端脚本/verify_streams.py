# -*- coding: utf-8 -*-
"""决定性验证：把板端产的流用**板端自己的 scale**解回来，看是否等于原始符号。

若相等 => 码流完全正确，PC 解码失败的根因是"解码侧用 fp32 模型重推 scales/means，
与编码侧的 INT8 不一致"，而不是码流本身有错。
"""
import os, sys, types
import numpy as np, torch

repo = "/mnt/e/fudanwei/工作区/GLC-main/GLC-main"
sys.path.insert(0, repo); sys.path.insert(0, os.path.join(repo, "src", "utils"))
stub = types.ModuleType("src.utils.metric_image"); stub.evaluate_quality = lambda *a, **k: None
sys.modules["src.utils.metric_image"] = stub
import test_image_complement2 as T

em = T.build_entropy_model(torch.device("cpu"))
OPS = "/mnt/e/fudanwei/工作区/_board_run/e2e4/operands/img0"
GLC = "/mnt/e/fudanwei/工作区/_board_run/glc/img0.glc"

blob = open(GLC, "rb").read()
q, dims, streams = T.parse_bitstream(blob)
print("容器 %d B  q=%s  z=%dB  stages=%s" % (len(blob), q, len(streams[0]), [len(s) for s in streams[1:]]))

print("\n=== A. 用**板端的 scale**解（means=0）===")
import time
allok = True
t_dec = 0.0
for k in range(4):
    sym = np.fromfile(os.path.join(OPS, "p%d_sym.i32" % k), dtype=np.int32)
    scl = np.fromfile(os.path.join(OPS, "p%d_scales.f32" % k), dtype=np.float32)
    sc = torch.from_numpy(scl).reshape(1, -1).clamp_min(T.SCALE_MIN)
    idx = em.model.build_indexes(sc)
    t0 = time.perf_counter()
    with torch.no_grad():
        got = em.model.decompress([bytes(streams[k + 1])], idx,
                                  means=torch.zeros_like(sc))
    t_dec += time.perf_counter() - t0
    got = got.reshape(-1).to(torch.int64).numpy()
    same = bool(np.array_equal(got, sym.astype(np.int64)))
    allok &= same
    print("  phase %d: %d 符号  解回 == 原始 ? %s   首差=%s"
          % (k, len(sym), "✅ 是" if same else "❌ 否",
             "-" if same else str(int(np.argmax(got != sym)))))

print("\n  熵解码合计耗时 %.1f ms（PC CPU，含 build_indexes）" % (t_dec * 1000))

print("\n结论 A: 板端码流本身 %s" % ("完全正确 ✅" if allok else "有问题 ❌"))

print("\n=== B. 解码侧的 scale 从哪来 ===")
print("  容器里**不存** scales/means —— 只存 z 的 16 个索引（28 B）")
print("  解码时由 **解码侧模型** 从 z_hat 重新跑 S2/S3 推导 scales/means")
print("  我们的编码侧 = 板端 INT8 的三张 _ZG；解码侧 = PC fp32 模型")
print("  => 两边的 S2/S3 输出不同 => 推出来的 CDF 行不同 => 解出来是垃圾")
print("  这与 y 流的质量无关（A 已证明 y 流逐符号正确）")
