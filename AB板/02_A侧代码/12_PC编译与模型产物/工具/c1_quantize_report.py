r"""对 C1 的 6 个子图跑 quantize（tf32，无需校准集），统计 NPU/CPU 归属分布"""
import json
import os
import subprocess
import sys
import time
from collections import Counter

ICRAFT = r"E:\fudanwei\Icraft-3.36.1\bin\icraft-quantize.exe"
RUN = os.environ.get("C1_RUN", r"E:\fudanwei\工作区\onnx\c1\run")

SUBS = ["s1_encoder_ga_hyper", "s2_hyperdec_fusion",
        "s3_phase1", "s3_phase2", "s3_phase3", "s4_gs_generator"]


def quantize(name):
    parsed = os.path.join(RUN, f"jr_{name}", f"{name}_parsed.json")
    raw = os.path.join(RUN, f"jr_{name}", f"{name}_parsed.raw")
    if not os.path.exists(parsed):
        return None, f"缺 parsed.json（parse 未成功？）"
    out = os.path.join(RUN, f"q_{name}")
    os.makedirs(out, exist_ok=True)
    t0 = time.time()
    p = subprocess.run(
        [ICRAFT, "--json", parsed, "--raw", raw, "--jr_path", out,
         "--qdtype", "tf32", "--target", "zhuge", "--log_path", RUN],
        capture_output=True, text=True, errors="replace",
    )
    el = time.time() - t0
    qj = os.path.join(out, f"{name}_quantized.json")
    if not os.path.exists(qj):
        return None, f"quantize 失败 exit={p.returncode} {el:.1f}s :: {p.stderr[-300:]}"
    return qj, f"{el:.1f}s"


def report(name, qj, note):
    net = json.load(open(qj, encoding="utf-8"))
    ops = net["ops"]
    c = Counter(o.get("compile_target", "?").replace("@", "") for o in ops)
    hosts = [(o["op_id"], o["_type_key"].split("::")[-1]) for o in ops
             if o.get("compile_target", "").replace("@", "").startswith("host")]
    npu = sum(v for k, v in c.items() if k.startswith("zhuget") or k.startswith("zg"))
    print(f"  {name:24s} {note}")
    print(f"      节点 {len(ops):5d} | NPU {npu:5d} | CPU {len(hosts):5d} | {dict(c)}")
    if hosts:
        names = Counter(t for _, t in hosts)
        print(f"      CPU 回退算子: {dict(names)}")
        if len(hosts) <= 8:
            print(f"      CPU op_id: {[i for i, _ in hosts]}")
    print()


if __name__ == "__main__":
    only = sys.argv[1:] or SUBS
    for name in only:
        qj, note = quantize(name)
        if qj is None:
            print(f"  {name:24s} ⚠️ {note}\n")
        else:
            report(name, qj, note)
