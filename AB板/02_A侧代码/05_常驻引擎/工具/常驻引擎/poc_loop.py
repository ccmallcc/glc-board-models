#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""poc_loop.py —— 收敛变量：常驻引擎里到底能不能反复 forward？

实验 A：只跑 S1 连续 6 次（同一个 session、同一个输入文件）
实验 B：按 s1->s2->s3p1->s3p2->s3p3 顺序轮 2 轮（模拟批量编码两张图）
用法: python3 /root/glc/poc_loop.py [A|B]
"""
import os
import sys
import time

sys.path.insert(0, "/root/glc")
import glc_rsd  # noqa: E402

CWD = {
    "s1": "/root/glc/run/s1",
    "s2": "/root/glc/run/s2",
    "s3p1": "/root/glc/run/s3p1",
    "s3p2": "/root/glc/run/s3p2",
    "s3p3": "/root/glc/run/s3p3",
}


def rss():
    try:
        for ln in open("/proc/self/status"):
            if ln.startswith("VmRSS"):
                return int(ln.split()[1]) // 1024
    except Exception:
        pass
    return -1


def main():
    mode = (sys.argv[1] if len(sys.argv) > 1 else "A").upper()
    print("=== poc_loop 模式 %s ===" % mode)
    e = glc_rsd.Engine()
    print("引擎就绪 %.3f s   RSS=%d MB" % (e.t_setup, rss()))

    if mode == "A":
        for i in range(1, 7):
            try:
                t0 = time.time()
                outs, _, w = e.run("s1", CWD["s1"])
                print("  A[%d] OK  %.3f s  out=%s  RSS=%d MB"
                      % (i, time.time() - t0, [o.shape for o in outs], rss()))
            except Exception as ex:
                print("  A[%d] !! 失败: %s: %s" % (i, type(ex).__name__, str(ex)[:200]))
                break
            sys.stdout.flush()
    else:
        order = ["s1", "s2", "s3p1", "s3p2", "s3p3"]
        for rnd in (1, 2, 3):
            print("--- 第 %d 轮 ---" % rnd)
            for k in order:
                try:
                    t0 = time.time()
                    outs, _, w = e.run(k, CWD[k])
                    print("  B[%d][%s] OK %.3f s  RSS=%d MB" % (rnd, k, time.time() - t0, rss()))
                except Exception as ex:
                    print("  B[%d][%s] !! 失败: %s: %s" % (rnd, k, type(ex).__name__, str(ex)[:200]))
                    print("LOOP_ABORT")
                    return
                sys.stdout.flush()
    print("LOOP_DONE")


if __name__ == "__main__":
    main()
