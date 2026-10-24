#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""plf_abab.py —— power_line_frequency 到底有没有用？用 A/B/A/B 交替测，排除漂移

第一版测出 Disabled 64.3 / 50Hz 81.0 / 60Hz 88.0，看着像有响应。
但那三个值是**按固定顺序**测的，单调上升 —— 这是**漂移**（AE 还在收敛 / 场景在变）
的典型特征，不是控制响应的特征。

判据：如果真有响应，值应该**跟着设置走**（A 高 B 低 A 高 B 低）；
      如果只是漂移，值会**跟着时间走**（一路升或一路降），和设置无关。
"""
import subprocess
import time

import cv2
import numpy as np

DEV = "/dev/video1"


def setplf(v):
    subprocess.run(["v4l2-ctl", "-d", DEV, "-c", "power_line_frequency=%d" % v],
                   capture_output=True)


def main():
    cap = cv2.VideoCapture(1)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    for _ in range(8):
        cap.read()

    seq = [(1, "50Hz"), (2, "60Hz"), (1, "50Hz"), (2, "60Hz"), (1, "50Hz"), (2, "60Hz")]
    print("  轮次  设置     均值    锐度(Laplacian方差)")
    rows = []
    for i, (v, nm) in enumerate(seq, 1):
        setplf(v)
        time.sleep(2.5)                      # 给 AE 足够时间收敛，别把收敛过程测进去
        ms, ls = [], []
        for _ in range(8):
            ok, f = cap.read()
            if ok:
                g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
                ms.append(float(g.mean()))
                ls.append(float(cv2.Laplacian(g, cv2.CV_64F).var()))
        m, l = np.mean(ms), np.mean(ls)
        rows.append((nm, m, l))
        print("  %-4d  %-7s  %6.2f   %8.1f" % (i, nm, m, l))

    a = [r[1] for r in rows if r[0] == "50Hz"]
    b = [r[1] for r in rows if r[0] == "60Hz"]
    print("\n  50Hz 均值序列: %s  (极差 %.2f)" % (["%.1f" % x for x in a], max(a) - min(a)))
    print("  60Hz 均值序列: %s  (极差 %.2f)" % (["%.1f" % x for x in b], max(b) - min(b)))
    print("  50Hz 平均 %.2f   60Hz 平均 %.2f   差 %.2f" % (np.mean(a), np.mean(b),
                                                        abs(np.mean(a) - np.mean(b))))
    drift = max(a + b) - min(a + b)
    print("\n  判据：真有效 -> 值跟着设置走(A/B 各自聚类稳定)；漂移 -> 值跟着时间单调走")
    print("  组内极差 50Hz=%.2f 60Hz=%.2f，整体极差=%.2f" % (max(a) - min(a), max(b) - min(b), drift))
    if max(a) - min(a) > abs(np.mean(a) - np.mean(b)) or max(b) - min(b) > abs(np.mean(a) - np.mean(b)):
        print("  ⇒ ★ 组内波动 >= 组间差异 ⇒ **看不出来有真实响应，之前的差异是漂移**")
    else:
        print("  ⇒ 组间差异明显大于组内波动 ⇒ 可能有真实响应，值得再验")
    cap.release()
    setplf(1)
    print("PLF_ABAB_DONE")


if __name__ == "__main__":
    main()
