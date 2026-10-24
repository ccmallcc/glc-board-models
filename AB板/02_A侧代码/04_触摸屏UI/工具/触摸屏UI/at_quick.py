#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""at_quick.py —— 30 秒电台体检：电台自己答不答 AT（不需要 B 端在场）

为什么单独写：`send_image.sh` 发图前只检查 /dev/ttyUSB0 存不存在，
**不检查电台是否真的活着**。如果电台没应答，用户按"发送"要等一整套重试才报错。
这里先量一下，把问题提前暴露。

A_send_session.py 期望的应答（它文件里的 WANT_AT）：
    AT+FREQ?   -> 470.110
    AT+SYMBOL? -> 19.2
    AT+UART?   -> 115200
"""
import os
import select
import sys
import termios
import time

DEV = "/dev/ttyUSB0"
BAUD = termios.B115200


def open_raw(dev, baud):
    fd = os.open(dev, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    a = termios.tcgetattr(fd)
    iflag, oflag, cflag, lflag, ispeed, ospeed, cc = a
    iflag = 0
    oflag = 0
    lflag = 0
    cflag = termios.CS8 | termios.CREAD | termios.CLOCAL
    cc = list(cc)
    cc[termios.VMIN] = 0
    cc[termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW,
                      [iflag, oflag, cflag, lflag, baud, baud, cc])
    termios.tcflush(fd, termios.TCIOFLUSH)
    return fd


def ask(fd, cmd, wait=1.2):
    termios.tcflush(fd, termios.TCIFLUSH)
    os.write(fd, (cmd + "\r\n").encode())
    buf = b""
    t0 = time.time()
    while time.time() - t0 < wait:
        r, _, _ = select.select([fd], [], [], 0.1)
        if r:
            try:
                d = os.read(fd, 4096)
            except OSError:
                break
            if d:
                buf += d
    return buf.decode("utf-8", "replace").strip()


def main():
    if not os.path.exists(DEV):
        print("!! 没有 %s" % DEV)
        return 2
    fd = open_raw(DEV, BAUD)
    print("已按 115200 8N1 打开 %s\n" % DEV)
    want = {"AT+FREQ?": "470.110", "AT+SYMBOL?": "19.2", "AT+UART?": "115200"}
    n_ok = 0
    for cmd in ("AT", "AT+FREQ?", "AT+SYMBOL?", "AT+UART?"):
        ans = ask(fd, cmd)
        exp = want.get(cmd)
        tag = ""
        if exp:
            ok = exp in ans
            n_ok += ok
            tag = "   <- 期望含 %s : %s" % (exp, "对" if ok else "**不对**")
        elif cmd == "AT" and ans:
            tag = "   <- 电台有回话"
        print("  %-12s -> %r%s" % (cmd, ans[:120], tag))
    os.close(fd)
    print("\n结论: %d/3 项期望值命中" % n_ok)
    print("AT_QUICK_DONE")
    return 0 if n_ok else 1


if __name__ == "__main__":
    sys.exit(main())
