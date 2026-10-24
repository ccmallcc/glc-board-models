#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""touch_probe.py —— 读 /dev/input/eventX，看触摸屏到底出不出事件（2026-10-14）

板上已经枚举出：
    N: Name="wch.cn USB2IIC_CTP_CONTROL"
    H: Handlers=event0
    B: EV=1b   (EV_SYN|EV_KEY|EV_ABS)
    B: KEY=400 (BTN_TOUCH)
    B: ABS=...03
本脚本把事件按 struct input_event 解出来打印，带时间戳，方便手指点一下就能看到。

struct input_event (64 位 Linux):
    struct timeval { __kernel_time_t tv_sec(8); __kernel_suseconds_t tv_usec(8); }  = 16 B
    __u16 type;  __u16 code;  __s32 value;                                          =  8 B
    合计 24 B

用法：
    python3 touch_probe.py [/dev/input/event0] [秒数]      # 前台跑，默认 30 秒
"""
import os
import struct
import sys
import time

DEV = sys.argv[1] if len(sys.argv) > 1 else "/dev/input/event0"
SECS = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
EV = struct.Struct("llHHi")          # tv_sec, tv_usec, type, code, value  -> 24 B
assert EV.size == 24, EV.size

TYPES = {0: "SYN", 1: "KEY", 2: "REL", 3: "ABS", 4: "MSC", 17: "LED", 21: "FF"}
CODES = {
    0: "SYN_REPORT", 2: "SYN_MT_REPORT", 4: "MSC_SCAN",
    0x110: "BTN_LEFT", 0x14A: "BTN_TOUCH", 0x145: "BTN_TOOL_FINGER",
    0x00: "ABS_X", 0x01: "ABS_Y", 0x18: "ABS_PRESSURE",
    0x2F: "ABS_MT_SLOT", 0x35: "ABS_MT_POSITION_X", 0x36: "ABS_MT_POSITION_Y",
    0x39: "ABS_MT_TRACKING_ID", 0x30: "ABS_MT_TOUCH_MAJOR",
    0x31: "ABS_MT_TOUCH_MINOR", 0x3A: "ABS_MT_PRESSURE",
}


def name(t, c):
    return "%s/%s" % (TYPES.get(t, str(t)), CODES.get(c, "0x%X" % c))


print("打开 %s，监听 %.0f 秒 ...（请用手指点/划屏幕）" % (DEV, SECS), flush=True)
try:
    fd = os.open(DEV, os.O_RDONLY | os.O_NONBLOCK)
except OSError as e:
    raise SystemExit("打不开 %s: %s" % (DEV, e))

t0 = time.time()
n = 0
pend = []
try:
    while time.time() - t0 < SECS:
        try:
            data = os.read(fd, EV.size * 64)
        except BlockingIOError:
            time.sleep(0.005)
            continue
        except OSError as e:
            print("读失败: %s" % e)
            break
        if not data:
            time.sleep(0.005)
            continue
        for off in range(0, len(data) - EV.size + 1, EV.size):
            sec, usec, typ, code, val = EV.unpack_from(data, off)
            n += 1
            if typ == 0 and code == 0:            # SYN_REPORT 收尾，打一组
                if pend:
                    print("  [+%.3fs] %s" % (time.time() - t0, "  ".join(pend)), flush=True)
                    pend = []
            else:
                pend.append("%s=%d" % (name(typ, code), val))
                if len(pend) > 8:
                    print("  [+%.3fs] %s" % (time.time() - t0, "  ".join(pend)), flush=True)
                    pend = []
finally:
    os.close(fd)

print("---")
print("共收到 %d 个 input 事件" % n)
print("TOUCH_PROBE_DONE")
