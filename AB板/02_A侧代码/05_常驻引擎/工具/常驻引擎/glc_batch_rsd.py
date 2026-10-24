#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""glc_batch_rsd.py —— 常驻引擎下的**批量编码**：一次载入，连编 N 张

为什么需要它
------------
`glc_board_full_rsd.py` 虽然用常驻引擎，但**每个进程仍然要把 5 个子图载入一次**（≈6.9 s）。
要摊薄这一次性成本，必须**在同一个进程里连编多张** —— 本脚本就是干这个。

用法（板子上）：
    python3 /root/glc/glc_batch_rsd.py name1=/path/a.ftmp name2=/path/b.ftmp ...

流程（每张图）：把输入 ftmp 拷到 run/s1/in0.ftmp → 调 glc_board_full.main()（内部走常驻引擎）
              → 容器在 pack/full_img0.glc → 存成 /root/glc/batch_out/<name>.glc 并算 md5
"""
import hashlib
import os
import shutil
import sys
import time

sys.path.insert(0, "/root/glc")

import icraft.xrt as _xrt           # noqa: E402

# ============================================================================
# ★★ 关键修补（2026-10-08 实测定位）★★
#   glc_board_full.py 在 [6/6] 的 PL rANS 段里有：
#       dev   = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
#       chunk = dev.defaultMemRegion().malloc(512*1024, False, 64)
#       reg   = RegWin()          # 新开 /dev/mem + mmap，从不关闭
#   ⇒ **每编码一张图就再开一次同一个 NPU 的设备句柄**。
#   实测症状：第一张图的 5 次 forward 全部正常，走到 [6/6] 之后，
#            第二张图的第一次 session.forward() 报
#                Exception info : Write failed
#                (AXIZG330AIPLDDRMemRegionNode::write -> AXIZG330AIUdmaMemRegionNode::write)
#   ⇒ 常驻 Session 依赖的 DMA 状态被第二次 Device.Open 打乱了。
#   修法：接管 xrt.Device.Open，**全进程只真开一次**，之后复用同一句柄。
#   （PL 段只是用它 malloc 一块 512 KB 的缓冲区 + 读写寄存器，复用句柄完全等价。）
# ============================================================================
_DEV = None
_ORIG_OPEN = _xrt.Device.Open


def _open_once(url):
    global _DEV
    if _DEV is None:
        _DEV = _ORIG_OPEN(url)
        print("### [修补] xrt.Device.Open 首次真开：%s" % url)
    else:
        print("### [修补] xrt.Device.Open 复用已有句柄（避免打乱 NPU DMA 状态）")
    return _DEV


_open_patched = False
try:
    _xrt.Device.Open = staticmethod(_open_once)
    _open_patched = True
    print("### [修补] 已接管 xrt.Device.Open")
except Exception as _e:
    print("### [修补] !! 无法接管 xrt.Device.Open: %s" % _e)

import glc_board_full as G          # noqa: E402
import glc_rsd                      # noqa: E402

OUTDIR = "/root/glc/batch_out"
IN0 = "/root/glc/run/s1/in0.ftmp"
PLGLC = "/root/glc/pack/full_img0.glc"

_engine = None


def _run_npu(key, cwd):
    global _engine
    if _engine is None:
        t = time.time()
        print("### GLC 常驻引擎：首次调用，载入 5 个子图（**整批只付这一次**）###")
        sys.stdout.flush()
        _engine = glc_rsd.Engine(G.MODELS)
        print("### 引擎就绪：%.3f s" % (time.time() - t))
        sys.stdout.flush()
    return _engine.run(key, cwd)


G.run_npu = _run_npu


def main():
    jobs = []
    for a in sys.argv[1:]:
        if "=" in a:
            n, p = a.split("=", 1)
        else:
            n, p = os.path.splitext(os.path.basename(a))[0], a
        jobs.append((n, p))
    if not jobs:
        print("用法: glc_batch_rsd.py name=/path/x.ftmp [name2=/path/y.ftmp ...]")
        sys.exit(2)
    if not os.path.isdir(OUTDIR):
        os.makedirs(OUTDIR)

    print("=" * 70)
    print("### 批量常驻编码：%d 张 ###" % len(jobs))
    for n, p in jobs:
        print("    %-12s <- %s (%d B)" % (n, p, os.path.getsize(p) if os.path.exists(p) else -1))
    print("=" * 70)
    sys.stdout.flush()

    t_boot = time.time()
    results = []
    for i, (n, p) in enumerate(jobs, 1):
        if not os.path.exists(p):
            print("[%d/%d] %s  !! 输入不存在，跳过" % (i, len(jobs), n))
            continue
        shutil.copyfile(p, IN0)
        sys.argv = ["glc_board_full_rsd.py", "--sample", "0"]
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
        if os.path.exists(PLGLC):
            shutil.copyfile(PLGLC, out)
            blob = open(out, "rb").read()
            got = (len(blob), hashlib.md5(blob).hexdigest())
        t_engine_so_far = (_engine.t_setup if _engine else 0.0)
        print("### [%d/%d] %-12s rc=%s  单张墙钟 %.3f s   容器 %s B  md5=%s"
              % (i, len(jobs), n, rc, dt,
                 got[0] if got else "?", got[1] if got else "?"))
        sys.stdout.flush()
        results.append((n, rc, dt, got))

    total = time.time() - t_boot
    print("=" * 70)
    if _engine is not None:
        print(_engine.summary())
    print("### 批量合计墙钟 %.3f s（其中引擎一次性 %.3f s）"
          % (total, _engine.t_setup if _engine else 0))
    if results:
        per = [r[2] for r in results]
        print("### 每张墙钟：min %.3f / 中位 %.3f / max %.3f s"
              % (min(per), sorted(per)[len(per) // 2], max(per)))
        first = results[0][2]
        if len(per) > 1:
            rest = per[1:]
            print("###   首张 %.3f s（含引擎载入） / 之后 %d 张平均 %.3f s"
                  % (first, len(rest), sum(rest) / len(rest)))
    print("### 容器清单（请与 icraft-run 版的 md5 对照）：")
    for n, rc, dt, got in results:
        print("###   %-12s %5s B  %s" % (n, got[0] if got else "?", got[1] if got else "?"))
    print("BATCH_RSD_DONE")


if __name__ == "__main__":
    main()
