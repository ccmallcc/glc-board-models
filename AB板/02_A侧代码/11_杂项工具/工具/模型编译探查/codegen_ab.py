# -*- coding: utf-8 -*-
r"""codegen A/B：把 adapt 的两份产物各生成一次代码，数算子并报告。

    A_baseline/  （adapt 默认，ZhugePadLayoutPass 开） → 期望 1116 op
    B_noPad/     （adapt --pass_off ZhugePadLayoutPass）→ 期望 ? op

产物：_exp_codegen\<tag>\s4_gs_generator_ZG.json / .raw
"""
import collections
import json
import os
import subprocess
import time

BIN = r"E:\fudanwei\Icraft-3.36.1\bin"
SRC = r"E:\fudanwei\_exp_adapt"
OUT = r"E:\fudanwei\_exp_codegen"
NAME = "s4_gs_generator"
TAGS = ["A_baseline", "B_noPad"]


def count(path):
    d = json.load(open(path, encoding="utf-8"))
    c = collections.Counter()
    for o in d.get("ops", []):
        tk = str(o.get("_type_key", "?")).split("::")[-1]
        nm = str(o.get("name", "?"))
        pre = nm.rsplit("_", 1)[0] if "_" in nm else nm
        c[pre or tk] += 1
    return len(d.get("ops", [])), c


def main():
    print("%-12s %8s %8s %10s %8s %9s  %s" %
          ("tag", "耗时s", "算子数", "Transpose", "Reshape", "ZG.raw MB", "rc"))
    print("-" * 90)
    for tag in TAGS:
        ad_j = os.path.join(SRC, tag, NAME + "_adapted.json")
        ad_r = os.path.join(SRC, tag, NAME + "_adapted.raw")
        gn = os.path.join(OUT, tag)
        os.makedirs(gn, exist_ok=True)
        gj = os.path.join(gn, NAME + "_ZG.json")
        cmd = [os.path.join(BIN, "icraft-generate.exe"),
               "--json", ad_j, "--raw", ad_r, "--jr_path", gn,
               "--log_path", os.path.join(gn, "log")]
        t0 = time.time()
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=7200)
        el = time.time() - t0
        txt = p.stdout.decode("utf-8", "replace")
        open(os.path.join(gn, "generate.txt"), "w", encoding="utf-8",
             errors="replace").write("CMD: " + " ".join(cmd) + "\n\n" + txt)
        if not os.path.exists(gj):
            tail = [l.strip() for l in txt.replace("\r", "\n").split("\n")
                    if l.strip() and "ConsoleMode" not in l]
            print("%-12s %8.0f %8s %10s %8s %9s  FAIL rc=%d  %s"
                  % (tag, el, "-", "-", "-", "-", p.returncode, " | ".join(tail[-3:])[:120]))
            continue
        n, c = count(gj)
        mb = os.path.getsize(gj.replace(".json", ".raw")) / 1e6 if os.path.exists(
            gj.replace(".json", ".raw")) else 0
        print("%-12s %8.0f %8d %10d %8d %9.1f  rc=%d"
              % (tag, el, n, c.get("Transpose", 0), c.get("Reshape", 0), mb, p.returncode))
    print("-" * 90)


if __name__ == "__main__":
    main()
