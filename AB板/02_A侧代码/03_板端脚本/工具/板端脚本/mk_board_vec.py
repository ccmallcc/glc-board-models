# -*- coding: utf-8 -*-
"""用 compressai 对我这份操作数编码，生成 rans_board 可吃的向量（含 EXPECTED_HEX）。
这样就能判定：板端 rANS 与 compressai 在**我的数据上**是否逐字节等价。"""
import os, sys, types
import numpy as np, torch

repo = "/mnt/e/fudanwei/工作区/GLC-main/GLC-main"
sys.path.insert(0, repo); sys.path.insert(0, os.path.join(repo, "src", "utils"))
stub = types.ModuleType("src.utils.metric_image"); stub.evaluate_quality = lambda *a, **k: None
sys.modules["src.utils.metric_image"] = stub
import test_image_complement2 as T

dev = torch.device("cpu")
em = T.build_entropy_model(dev)
SCALE_MIN = T.SCALE_MIN

ops = sys.argv[1]          # 例如 .../operands/img0
out = sys.argv[2]          # 输出向量文件
idx_phase = int(sys.argv[3])
odir = os.path.dirname(out)
os.makedirs(odir, exist_ok=True)

sym = np.fromfile(os.path.join(ops, "p%d_sym.i32" % idx_phase), dtype=np.int32)
scl = np.fromfile(os.path.join(ops, "p%d_scales.f32" % idx_phase), dtype=np.float32)
print("phase %d: %d 符号  scale[%.4f, %.4f]" % (idx_phase, len(sym), scl.min(), scl.max()))

# 把符号当 values、means=0 传进去 —— compressai 内部 quantize(values,"symbols",0)=round(values)=sym
values = torch.from_numpy(sym.astype(np.float32)).reshape(1, -1)
scales = torch.from_numpy(scl).reshape(1, -1).clamp_min(SCALE_MIN)
means = torch.zeros_like(values)
with torch.no_grad():
    indexes = em.model.build_indexes(scales)
    payload = em.model.compress(values, indexes, means=means)[0]
    idx = indexes.reshape(-1).to(torch.int64).numpy()

sc_bits = np.frombuffer(np.ascontiguousarray(scl).tobytes(), dtype=np.uint32)
print("  compressai payload = %d B，CDF 行 %d，index[%d,%d]"
      % (len(payload), len(set(idx.tolist())), idx.min(), idx.max()))

with open(out, "w", encoding="utf-8") as f:
    f.write("# exported from compressai, values=symbols means=0\n")
    f.write("PRECISION 16\n")
    f.write("NUM_SYMBOLS %d\n" % len(sym))
    f.write("SYMBOLS " + " ".join(str(int(v)) for v in sym.tolist()) + "\n")
    f.write("SCALES " + " ".join("%08x" % int(v) for v in sc_bits.tolist()) + "\n")
    f.write("EXPECTED_LEN %d\n" % len(payload))
    f.write("EXPECTED_HEX " + payload.hex() + "\n")
print("->", out)
