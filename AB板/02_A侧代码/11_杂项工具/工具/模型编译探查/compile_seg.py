# -*- coding: utf-8 -*-
r"""compile_seg.py —— 把切好的子图真编译一遍，数 icraft 层面的算子数。

目的：验证 B 侧那张分段表的"op 总数"列（86 / 148 / 147 / 31）到底是不是真读出来的。
      —— 那 4 个数与 29 号文"节点"列**逐个相同**，而 29 号文的 GB 列又反证真实节点数是
         105 / 400 / 79 / 78 / 12。先编译两个小段（dec 105 节点、b4 12 节点）对一下。

用法: python compile_seg.py s4a_dec s4b4
"""
import collections
import json
import os
import shutil
import subprocess
import sys
import time

BIN = r"E:\fudanwei\Icraft-3.36.1\bin"
PIPELINE = r"E:\fudanwei\GLC-共享包\工具\c1_pipeline.py"
SEGDIR = r"E:\fudanwei\_seg_probe"
OUTROOT = r"E:\fudanwei\_seg_compile"
DTYPE = "fp16"


def run(cmd, log, expect=None, timeout=7200):
    t0 = time.time()
    with open(log, "w", encoding="utf-8", errors="replace") as f:
        f.write("CMD: " + " ".join(cmd) + "\n\n")
        f.flush()
        p = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=timeout)
    return ((expect is None) or os.path.exists(expect)), time.time() - t0, p.returncode


def count_ops(j):
    d = json.load(open(j, encoding="utf-8"))
    c = collections.Counter()
    for o in d.get("ops", []):
        nm = str(o.get("name", "?"))
        c[nm.rsplit("_", 1)[0] if "_" in nm else str(o.get("_type_key", "?")).split("::")[-1]] += 1
    return len(d.get("ops", [])), c


def main():
    targets = sys.argv[1:] or ["s4a_dec"]
    for name in targets:
        # 支持 "名字=绝对路径.onnx"
        if "=" in name:
            name, src = name.split("=", 1)
        else:
            src = os.path.join(SEGDIR, name + ".onnx")
        if not os.path.exists(src):
            print("%-10s MISSING %s" % (name, src)); continue
        # 取输入形状（ONNX 是 NCHW）→ NHWC
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import onnx
        g = onnx.load(src)
        dims = [d.dim_value for d in g.graph.input[0].type.tensor_type.shape.dim]
        n, c_, h, w = [(x if x else 1) for x in dims]      # 0 = 未知维度，归一成 1
        nhwc = "%d,%d,%d,%d" % (n, h, w, c_)
        out = os.path.join(OUTROOT, name)
        os.makedirs(out, exist_ok=True)
        pj = os.path.join(out, name + "_parsed.json")
        pr = pj.replace("_parsed.json", "_parsed.raw")

        cmd = [os.path.join(BIN, "icraft-parse.exe"),
               "--net_name", name, "--network", src, "--jr_path", out,
               "--framework", "ONNX", "--target", "zhuge",
               "--inputs_dtype", "FP32", "--inputs", nhwc, "--inputs_layout", "NHWC",
               "--pre_method", "nop",
               "--pre_scale", ",".join(["1.0"] * c_),
               "--pre_mean", ",".join(["0.0"] * c_),
               "--channel_swap", ",".join(str(i) for i in range(c_))]
        ok, dt, rc = run(cmd, os.path.join(out, "parse.txt"), pj)
        print("%-10s(%s)  parse  %s %6.1fs" % (name, nhwc, "ok" if ok else "FAIL", dt), flush=True)
        if not ok:
            print(open(os.path.join(out, "parse.txt"), encoding="utf-8", errors="replace").read()[-600:])
            continue

        cmd = [sys.executable, PIPELINE, "--parsed", pj, "--raw", pr, "--dtype", DTYPE,
               "--outdir", out, "--stages", "optimize,quantize,adapt,generate"]
        gen = os.path.join(out, "gen", name + "_ZG.json")
        ok, dt, rc = run(cmd, os.path.join(out, "pipeline.txt"), gen)
        if not ok:
            print("%-10s pipeline FAIL %6.1fs rc=%d" % (name, dt, rc))
            print(open(os.path.join(out, "pipeline.txt"), encoding="utf-8",
                       errors="replace").read()[-800:])
            continue
        n_op, cnt = count_ops(gen)
        print("%-10s pipeline ok %6.1fs  ★ icraft 算子数 = %d   (ONNX 节点 %d, 比值 %.2f×)  %s"
              % (name, dt, n_op, len(g.graph.node), n_op / max(1, len(g.graph.node)),
                 "  ".join("%s=%d" % kv for kv in cnt.most_common(6))), flush=True)
    print("COMPILE_SEG_DONE")


if __name__ == "__main__":
    main()
