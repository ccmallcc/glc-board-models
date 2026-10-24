#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""probe_backend.py —— 查"算子到底跑在哪个后端"（H=Host/CPU, Z=ZG330/NPU）

为什么需要：实测发现**整个项目（编码 s1 + 解码 s4）的算子 100% 标 (H)**，
ZG330 NPU 全程闲置。把 `--backends` 里的 `;Host` 去掉只留 ZG330 会直接
`Check failed: (is_bound) is false`。这个脚本把这件事一键复现，便于对比不同
编译/量化参数下的结果。

用法：
    python3 probe_backend.py s1            # 编码端 s1（407 ms，模型小，最适合做实验）
    python3 probe_backend.py s4_int8       # 解码端 s4
    python3 probe_backend.py s1 nolocal    # 不给 Host 兜底，看 ZG330 接不接得住
"""
import os
import re
import subprocess
import sys
import time

MODELS = "/root/glc/models"
CAND = {
    "s1":     ("s1_encoder_ga_hyper_ZG", "/root/glc/run/s1", "in0.ftmp"),
    "s2":     ("s2_hyperdec_fusion_ZG", None, None),
    "s4_int8": ("s4_int8/s4_gs_generator_ZG", "/root/tp5603_drv/decode_run/run_s4", "in0.ftmp"),
    "s4_bf16": ("s4_bf16/s4_gs_generator_ZG", "/root/tp5603_drv/decode_run/run_s4", "in0.ftmp"),
}


def main():
    key = sys.argv[1] if len(sys.argv) > 1 else "s1"
    noguest = len(sys.argv) > 2 and sys.argv[2] == "nolocal"
    if key not in CAND:
        raise SystemExit("可选: %s" % ", ".join(CAND))
    name, cwd, inp = CAND[key]
    base = os.path.join(MODELS, name)
    backends = "ZG330,axi://zg330aiu" if noguest else "ZG330,axi://zg330aiu;Host"
    print("模型 %s  后端 %s  cwd=%s" % (base, backends, cwd))
    argv = ["icraft-run", "--json", base + ".json", "--raw", base + ".raw",
            "--backends", backends, "--log_time", "--log_path", "/tmp/bklog"]
    if cwd and inp:
        argv += ["--input", inp]
    t0 = time.time()
    p = subprocess.run(argv, cwd=cwd or "/tmp", stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT)
    dt = time.time() - t0
    out = p.stdout.decode("utf-8", "replace")
    open("/root/probe_backend_%s.log" % key, "w").write(out)
    print("  rc=%d  墙钟 %.1f s" % (p.returncode, dt))
    tally = {}
    for m in re.finditer(r"opType: [A-Za-z0-9_]*\(([A-Za-z]*)\)", out):
        tally[m.group(1)] = tally.get(m.group(1), 0) + 1
    print("  ★ 后端计数: %s" % (tally or "(没跑到算子)"))
    if not tally:
        for ln in out.splitlines():
            if "Exception info" in ln or "Check failed" in ln:
                print("    " + ln.strip()[:160])
    for ln in out.splitlines():
        if ln.startswith("total_time") or ln.startswith("OpNum 3") or "Transpose" in ln and "OpNum" in ln:
            print("    " + ln.strip())


if __name__ == "__main__":
    main()
