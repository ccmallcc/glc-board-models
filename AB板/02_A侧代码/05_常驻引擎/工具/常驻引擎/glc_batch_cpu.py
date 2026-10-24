#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""glc_batch_cpu.py —— 常驻引擎 + **CPU 打包**的批量编码（GLC 2026-10-09）

与 glc_batch_rsd.py 的区别：**把 PL rANS 段整个换掉**。
  · 常驻引擎（glc_rsd.Engine）不变 —— 5 个子图只载入一次，之后每帧 forward
  · 但 [6/6] 不再走 PL rANS，改用 A53 CPU 的 glc2_pack（glc_rsd_cpu.patch）
  ⇒ 于是 `glc_board_full.py` 里"每张图再 Open 一次 NPU"和"每张图再 mmap 一次 /dev/mem"
    这两个包袱**一起消失**，正好是上一轮批量失败的疑点所在。

用法：
    python3 /root/glc/glc_batch_cpu.py p1=/root/glc/inputs_photo/p1.ftmp p2=...
"""
import hashlib
import os
import shutil
import sys
import time

sys.path.insert(0, "/root/glc")

import glc_board_full as G          # noqa: E402
import glc_rsd                      # noqa: E402
import glc_rsd_cpu                  # noqa: E402

OUTDIR = "/root/glc/batch_out_cpu"
IN0 = "/root/glc/run/s1/in0.ftmp"
PLGLC = "/root/glc/pack/full_img0.glc"

_engine = None


def _run_npu(key, cwd):
    global _engine
    if _engine is None:
        t = time.time()
        print("### [常驻引擎] 载入 5 个子图（整批只付这一次）###")
        sys.stdout.flush()
        _engine = glc_rsd.Engine(G.MODELS)
        print("### [常驻引擎] 就绪：%.3f s" % (time.time() - t))
        sys.stdout.flush()
    return _engine.run(key, cwd)


def main():
    # ★ 先打补丁（必须在建引擎之前，这样设备句柄只真开一次）
    applied = glc_rsd_cpu.patch(G)
    print("### [补丁] " + " / ".join(applied))
    G.run_npu = _run_npu

    jobs = []
    for a in sys.argv[1:]:
        if "=" in a:
            n, p = a.split("=", 1)
        else:
            n, p = os.path.splitext(os.path.basename(a))[0], a
        jobs.append((n, p))
    if not jobs:
        print("用法: glc_batch_cpu.py name=/path/x.ftmp ...")
        sys.exit(2)
    if not os.path.isdir(OUTDIR):
        os.makedirs(OUTDIR)

    print("=" * 74)
    print("### 批量（常驻引擎 + CPU 打包）：%d 张 ###" % len(jobs))
    print("=" * 74)
    sys.stdout.flush()

    t_boot = time.time()
    results = []
    for i, (n, p) in enumerate(jobs, 1):
        if not os.path.exists(p):
            print("[%d/%d] %s  !! 输入不存在，跳过" % (i, len(jobs), n))
            continue
        shutil.copyfile(p, IN0)
        sys.argv = ["glc_board_full.py", "--sample", "0"]
        t0 = time.time()
        rc = None
        try:
            rc = G.main()
        except SystemExit as e:
            rc = e.code
        except Exception as e:
            import traceback
            traceback.print_exc()
            rc = "EXC:%s" % e
        dt = time.time() - t0

        out = os.path.join(OUTDIR, "%s.glc" % n)
        got = None
        # ★ 只有 rc==0 才拷结果 —— 否则会把上一次的残留容器报成"本张的结果"（上一轮就吃了这个亏）
        if rc == 0 and os.path.exists(PLGLC):
            shutil.copyfile(PLGLC, out)
            blob = open(out, "rb").read()
            got = (len(blob), hashlib.md5(blob).hexdigest())
        elif rc != 0:
            got = None
        print("### [%d/%d] %-10s rc=%s  单张墙钟 %.3f s  容器 %s B  md5=%s"
              % (i, len(jobs), n, rc, dt, got[0] if got else "?", got[1] if got else "?"))
        sys.stdout.flush()
        results.append((n, rc, dt, got))

    total = time.time() - t_boot
    print("=" * 74)
    if _engine is not None:
        print(_engine.summary())
    print(glc_rsd_cpu.summary())
    print("### 批量合计墙钟 %.3f s（引擎一次性 %.3f s）"
          % (total, _engine.t_setup if _engine else 0))
    if results:
        per = [r[2] for r in results]
        print("### 每张墙钟：min %.3f / 中位 %.3f / max %.3f s"
              % (min(per), sorted(per)[len(per) // 2], max(per)))
        if len(per) > 1:
            print("###   首张 %.3f s（含引擎载入） / 之后 %d 张平均 %.3f s"
                  % (per[0], len(per) - 1, sum(per[1:]) / (len(per) - 1)))
    print("### 容器清单：")
    for n, rc, dt, got in results:
        print("###   %-10s %5s B  %s" % (n, got[0] if got else "?", got[1] if got else "?"))
    print("BATCH_CPU_DONE")


if __name__ == "__main__":
    main()
