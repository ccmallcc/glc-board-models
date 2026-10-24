# -*- coding: utf-8 -*-
r"""再试：把厂商带了但默认没启用的 pass 用 --pass_on 挂上去，看 Transpose 会不会掉。

基准（adapt 默认，同一条输入 quantized）：
    1844 op / Transpose 494 / Reshape 660      （耗时 137 s）
文档摘录：
    icraft.OptimizeLayoutPass         Optimizer 排布优化 不会影响精度 独立
                                      "根据后端特点调整 layernorm 算子前的特征图形状，提高计算速度"
    icraft.DeepOptimizeTransDataSeqPass  在 zhuge/optimizer.toml 的 common 里，但 adapt 没挂
    icraft.RemoveUselessTranspose1Pass   在 zhuge/optimizer.toml 的 common 里，但 adapt 没挂
"""
import collections
import json
import os
import subprocess
import time

BIN = r"E:\fudanwei\Icraft-3.36.1\bin"
SRC = r"E:\fudanwei\工作区\compile2\s4_int8\s4_gs_generator_quantized"
OUT = r"E:\fudanwei\_exp_adapt"

CASES = [
    ("P1_OptimizeLayout",   ["--pass_on", "icraft.OptimizeLayoutPass"]),
    ("P2_DeepOptTransData", ["--pass_on", "icraft.DeepOptimizeTransDataSeqPass"]),
    ("P3_RemoveUselessTr",  ["--pass_on", "icraft.RemoveUselessTranspose1Pass"]),
]


def count(path):
    d = json.load(open(path, encoding="utf-8"))
    c = collections.Counter()
    for o in d.get("ops", []):
        nm = str(o.get("name", "?"))
        c[nm.rsplit("_", 1)[0] if "_" in nm else nm] += 1
    return len(d.get("ops", [])), c


def main():
    print("基准 A_baseline: 1844 op / Transpose 494 / Reshape 660")
    print("%-20s %7s %8s %10s %8s  %s" % ("case", "耗时s", "算子数", "Transpose", "Reshape", "备注"))
    print("-" * 88)
    for tag, extra in CASES:
        od = os.path.join(OUT, tag)
        os.makedirs(od, exist_ok=True)
        cmd = [os.path.join(BIN, "icraft-adapt.exe"),
               "--json", SRC + ".json", "--raw", SRC + ".raw",
               "--jr_path", od, "--target", "zhuge",
               "--log_path", os.path.join(od, "log")] + extra
        t0 = time.time()
        try:
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=3600)
        except subprocess.TimeoutExpired:
            print("%-20s %7s %8s %10s %8s  TIMEOUT" % (tag, ">3600", "-", "-", "-"))
            continue
        el = time.time() - t0
        txt = p.stdout.decode("utf-8", "replace")
        open(os.path.join(od, "adapt.txt"), "w", encoding="utf-8", errors="replace").write(
            "CMD: " + " ".join(cmd) + "\n\n" + txt)
        js = [f for f in os.listdir(od) if f.endswith(".json")]
        if p.returncode != 0 or not js:
            tail = [l.strip() for l in txt.replace("\r", "\n").split("\n")
                    if l.strip() and "ConsoleMode" not in l]
            print("%-20s %7.0f %8s %10s %8s  rc=%d %s"
                  % (tag, el, "-", "-", "-", p.returncode, " | ".join(tail[-2:])[:110]))
            continue
        js.sort(key=lambda f: -os.path.getsize(os.path.join(od, f)))
        n, c = count(os.path.join(od, js[0]))
        print("%-20s %7.0f %8d %10d %8d  %s"
              % (tag, el, n, c.get("Transpose", 0), c.get("Reshape", 0), js[0]))
    print("-" * 88)


if __name__ == "__main__":
    main()
