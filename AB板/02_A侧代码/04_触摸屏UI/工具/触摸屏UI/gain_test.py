#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gain_test.py —— 实测 UVC 的 gain / brightness 到底有没有用（决定"曝光"怎么调）

背景：这块 HD 720P Webcam (0c45:6341, UVC 1.00) **没有任何 exposure_* 控制项**，
      `v4l2-ctl -C exposure_absolute` 实测报 unknown control。
      所以"调曝光"只能用能调的那些旋钮。本脚本逐个量：设一个值，抓一帧，看均值。
"""
import subprocess
import sys
import time

import cv2
import numpy as np

DEV = 1


def setc(name, val):
    r = subprocess.run(["v4l2-ctl", "-d", "/dev/video%d" % DEV, "-c", "%s=%d" % (name, val)],
                       capture_output=True, text=True)
    return r.returncode == 0, (r.stderr or r.stdout).strip()


def main():
    cap = cv2.VideoCapture(DEV)
    if not cap.isOpened():
        raise SystemExit("摄像头打不开")
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    for _ in range(5):
        cap.read()

    def grab(settle=0.6, n=4):
        time.sleep(settle)
        last = None
        for _ in range(n):
            ok, f = cap.read()
            if ok:
                last = f
        return last

    print("=== 基准（不设任何值）===")
    f = grab()
    print("   mean=%6.2f  std=%6.2f  min=%d max=%d" % (f.mean(), f.std(), f.min(), f.max()))

    for name, vals in (("gain", [0, 25, 50, 75, 100]),
                       ("brightness", [-64, -32, 0, 32, 64]),
                       ("backlight_compensation", [0, 1, 2])):
        print("\n=== %s ===" % name)
        for v in vals:
            ok, msg = setc(name, v)
            if not ok:
                print("   %-4s 设置失败: %s" % (v, msg))
                continue
            f = grab()
            if f is None:
                print("   %-4s 抓帧失败" % v)
                continue
            print("   %-4s mean=%6.2f  std=%6.2f  max=%d" % (v, f.mean(), f.std(), f.max()))
        setc(name, {"gain": 0, "brightness": 0, "backlight_compensation": 1}[name])

    cap.release()
    print("\nGAIN_TEST_DONE")


if __name__ == "__main__":
    main()
