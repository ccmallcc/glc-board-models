#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""shutter_probe.py —— 这块摄像头到底能不能设"快门速度"（曝光时间）？

之前的结论（v4l2-ctl --list-ctrls 只有 brightness/contrast/.../backlight_compensation，
`v4l2-ctl -C exposure_absolute` 报 unknown control）只说明**驱动没暴露**，
不能说明**硬件不支持**。真正的判据在 UVC 描述符里：
  VideoControl 接口 → Camera Terminal 描述符（bDescriptorType=0x24, bDescriptorSubtype=0x02）
  的 bmControls 位图：
      D0 Scanning Mode        D1 Auto-Exposure Mode    D2 Auto-Exposure Priority
      D3 Exposure Time(Abs)   D4 Exposure Time(Rel)    D5/D6 Focus
      D7/D8 Iris              D9/D10 Zoom              ...
  D3 = 0 ⇒ 摄像头**硬件层就没有**绝对曝光时间控制 ⇒ 快门速度根本设不了，没有别的路。
  D3 = 1 而驱动不暴露 ⇒ 理论上还有别的途径（libuvc / 原始 UVC）。

顺带测 `power_line_frequency`（供电频率/抗闪烁）—— 这是唯一还没试过的旋钮，
它会影响固件允许选的曝光档位（50Hz -> 1/100s 档，60Hz -> 1/120s 档）。
"""
import glob
import os
import subprocess
import sys
import time

DEV = "/dev/video1"

CTRL_NAMES = {
    0: "Scanning Mode", 1: "Auto-Exposure Mode", 2: "Auto-Exposure Priority",
    3: "Exposure Time (Absolute)", 4: "Exposure Time (Relative)",
    5: "Focus (Absolute)", 6: "Focus (Relative)", 7: "Iris (Absolute)",
    8: "Iris (Relative)", 9: "Zoom (Absolute)", 10: "Zoom (Relative)",
    11: "PanTilt (Absolute)", 12: "PanTilt (Relative)", 13: "Roll (Absolute)",
    14: "Roll (Relative)", 17: "Focus, Auto", 18: "Privacy",
}
PU_NAMES = {
    0: "Brightness", 1: "Contrast", 2: "Hue", 3: "Saturation", 4: "Sharpness",
    5: "Gamma", 6: "White Balance Temperature", 7: "White Balance Component",
    8: "Backlight Compensation", 9: "Gain", 10: "Power Line Frequency",
    11: "Hue, Auto", 12: "White Balance Temperature, Auto", 13: "Digital Multiplier",
    14: "Digital Multiplier Limit", 15: "Analog Video Standard", 16: "Analog Video Lock Status",
}


def find_videocontrol_descriptors():
    """把 USB 配置描述符里 VideoControl 接口下的所有 class-specific 描述符挖出来"""
    out = []
    for d in glob.glob("/sys/bus/usb/devices/*/descriptors"):
        try:
            blob = open(d, "rb").read()
        except OSError:
            continue
        # 先看这个设备是不是我们的摄像头（VID:PID 0c45:6341）
        sysf = os.path.dirname(d)
        try:
            vid = open(sysf + "/idVendor").read().strip()
            pid = open(sysf + "/idProduct").read().strip()
        except OSError:
            continue
        if (vid, pid) != ("0c45", "6341"):
            continue
        out.append((sysf, blob))
    return out


def walk(blob):
    """顺序扫描述符链：9 字节标准描述符（bLength=9,bDescriptorType=2/4/5），
       以及 bDescriptorType>=0x21 的 class-specific 描述符（长度在第一个字节）"""
    i = 0
    n = len(blob)
    cur_if = None
    found = []
    while i + 2 <= n:
        ln = blob[i]
        if ln < 2 or i + ln > n:
            break
        typ = blob[i + 1]
        if typ == 0x04 and ln >= 9:                 # INTERFACE
            cur_if = (blob[i + 5], blob[i + 6], blob[i + 7])   # class, subclass, protocol
            i += ln
            continue
        if ln >= 9 and typ == 0x05:                 # ENDPOINT
            i += ln
            continue
        if ln >= 3 and typ in (0x24, 0x25) and cur_if and cur_if[0] == 0x0E:
            found.append((cur_if, typ, blob[i:i + ln]))
        i += ln
    return found


def main():
    devs = find_videocontrol_descriptors()
    if not devs:
        print("!! 没找到 0c45:6341 的 USB 描述符")
        return 2
    sysf, blob = devs[0]
    print("设备 %s  (%s)" % (sysf, os.path.basename(sysf)))
    print("描述符 %d B" % len(blob))

    ents = walk(blob)
    print("\n=== VideoControl 接口下的 class-specific 描述符（0x24=VC, 0x25=VS）===")
    for cur_if, typ, d in ents:
        print("  type=0x%02x len=%d subtype=0x%02x  %s"
              % (typ, len(d), d[2] if len(d) > 2 else 0, d.hex()))

    print("\n=== Camera Terminal（0x24 / 0x02）的 bmControls ===")
    hit = False
    for cur_if, typ, d in ents:
        if typ == 0x24 and len(d) > 2 and d[2] == 0x02:
            hit = True
            cs_i = 14 if len(d) > 15 else 8
            csize = d[cs_i]
            bm = int.from_bytes(d[cs_i + 1:cs_i + 1 + csize], "little")
            print("  bControlSize=%d  bmControls=0x%06x" % (csize, bm))
            for bit in sorted(CTRL_NAMES):
                print("    D%-2d %-28s %s" % (bit, CTRL_NAMES[bit],
                                              "★ 支持" if (bm >> bit) & 1 else "不支持"))
    if not hit:
        print("  (没找到 Camera Terminal 描述符)")

    print("\n=== Processing Unit（0x24 / 0x03）的 bmControls ===")
    for cur_if, typ, d in ents:
        if typ == 0x24 and len(d) > 2 and d[2] == 0x03:
            csize = d[7] if len(d) > 7 else 0
            bm = int.from_bytes(d[8:8 + csize], "little")
            print("  bControlSize=%d  bmControls=0x%04x" % (csize, bm))
            for bit in sorted(PU_NAMES):
                if (bm >> bit) & 1:
                    print("    D%-2d %s" % (bit, PU_NAMES[bit]))

    print("\n=== v4l2-ctl 实际暴露的控制项 ===")
    r = subprocess.run(["v4l2-ctl", "-d", DEV, "--list-ctrls"], capture_output=True, text=True)
    for ln in r.stdout.splitlines():
        if ln.strip():
            print("  " + ln.strip())

    print("\n=== 试最后一个没试过的旋钮：power_line_frequency（抗闪烁）===")
    import cv2
    cap = cv2.VideoCapture(int(DEV.replace("/dev/video", "")))
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    for _ in range(5):
        cap.read()
    for v, nm in ((0, "Disabled"), (1, "50 Hz"), (2, "60 Hz")):
        subprocess.run(["v4l2-ctl", "-d", DEV, "-c", "power_line_frequency=%d" % v],
                       capture_output=True)
        time.sleep(0.8)
        fs = []
        for _ in range(6):
            ok, f = cap.read()
            if ok:
                fs.append(f)
        if not fs:
            print("  %-9s 抓帧失败" % nm)
            continue
        import numpy as np
        g = [cv2.cvtColor(x, cv2.COLOR_BGR2GRAY) for x in fs]
        lap = [cv2.Laplacian(x, cv2.CV_64F).var() for x in g]
        dif = [float(np.abs(g[i].astype(int) - g[i - 1].astype(int)).mean())
               for i in range(1, len(g))]
        print("  %-9s 均值 %6.2f  Laplacian方差(锐度) %8.1f  帧间差 %6.3f"
              % (nm, np.mean([x.mean() for x in fs]), np.mean(lap),
                 np.mean(dif) if dif else 0))
    cap.release()
    subprocess.run(["v4l2-ctl", "-d", DEV, "-c", "power_line_frequency=1"], capture_output=True)
    print("\nSHUTTER_PROBE_DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
