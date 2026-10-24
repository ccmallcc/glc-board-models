#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""at_quick2.py —— 电台 AT 体检（**严格照抄 A_send_session.py 的时序**）

★ 为什么有第二版：
   我的 at_quick.py 直接发 `AT+FREQ?` —— **漏了最关键的 `+++`**。
   这块 DTU 默认在**透传模式**，不透传 `+++` 进命令模式的话，AT 命令一律石沉大海。
   所以 at_quick.py 报"0/3 应答"是**我的探针错了**，不是电台坏了。
   （项目里已经有过一次同类误判，记在 45 号文档附近。）

本脚本逐行对齐 A_send_session.py 的自检段：
        drain(fd, 2.0)                 # 清缓冲 2 秒
        at(fd, '+++', 1.5)             # 进命令模式  ← 上一版漏的就是这句
        for cmd, want in WANT_AT:      # 三条参数查询，每条重试 3 次
            at_retry(fd, cmd, want, tries=3)
        at(fd, 'AT+EXIT=1', 1.2)       # 回透传模式（= 正常发数据的模式）

跑完电台停在**透传模式**，和跑之前一样，不会影响后面 send_image.sh 发图。
"""
import os
import select
import sys
import termios
import time

DEV = os.environ.get("GLC_RADIO_DEV", "/dev/ttyUSB0")
BAUDMAP = {9600: termios.B9600, 19200: termios.B19200, 115200: termios.B115200}
WANT_AT = (("AT+FREQ?", "470.110"), ("AT+SYMBOL?", "19.2"), ("AT+UART?", "115200"))


def open_dev(baud=115200):
    fd = os.open(DEV, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    a = termios.tcgetattr(fd)
    iflag, oflag, cflag, lflag, ispeed, ospeed, cc = a
    iflag = oflag = lflag = 0
    cflag = termios.CS8 | termios.CREAD | termios.CLOCAL
    ispeed = ospeed = BAUDMAP[baud]
    cc[termios.VMIN] = 0
    cc[termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, [iflag, oflag, cflag, lflag, ispeed, ospeed, cc])
    try:
        termios.tcflush(fd, termios.TCIOFLUSH)
    except Exception:
        pass
    return fd


def drain(fd, secs):
    """和 A_send_session.py 的 drain 同义：读 secs 秒，返回读到的字节"""
    t0 = time.time()
    out = b""
    while time.time() - t0 < secs:
        r, _, _ = select.select([fd], [], [], 0.05)
        if r:
            try:
                d = os.read(fd, 4096)
            except OSError:
                break
            if d:
                out += d
    return out


def at(fd, cmd, wait=1.0):
    os.write(fd, (cmd + "\r\n").encode())
    return drain(fd, wait)


def at_retry(fd, cmd, want=None, tries=3, wait=1.0):
    got = ""
    for k in range(tries):
        r = at(fd, cmd, wait).decode("utf-8", "replace").strip()
        print("      %-11s 第%d次 -> %r" % (cmd, k + 1, r[:80]))
        if r and (want is None or want in r):
            return r
        if len(r) > len(got):
            got = r
    return got


def main():
    if not os.path.exists(DEV):
        print("!! 找不到 %s" % DEV)
        return 2
    fd = open_dev(115200)
    print("打开 %s @115200 8N1\n" % DEV)

    print("[1] 清缓冲 2.0 s …")
    pre = drain(fd, 2.0)
    print("    清掉 %d B 残留" % len(pre))

    print("[2] 发 '+++' 进命令模式（← 上一版漏掉的这一步）")
    r = at(fd, "+++", 1.5)
    print("    '+++' -> %r" % r[:80].decode("utf-8", "replace") if r else "    '+++' -> (无回显，有些 DTU 进命令模式不吭声，属正常)")

    print("[3] 参数查询（每条重试 3 次，对齐 A_send_session.py）")
    ok = True
    for cmd, want in WANT_AT:
        resp = at_retry(fd, cmd, want, tries=3)
        hit = want in resp
        ok = ok and hit
        print("    => %-11s 期望含 %-8s [%s]" % (cmd, want, "OK" if hit else "不符"))

    print("[4] AT+EXIT=1 回透传模式")
    r = at(fd, "AT+EXIT=1", 1.2).decode("utf-8", "replace").strip()
    print("    -> %r  %s" % (r[:60], "[含 OK，已进透传]" if "OK" in r else "[!! 没进透传]"))

    os.close(fd)
    print("\n结论: %s" % ("电台自检 3/3 通过，可以发图" if ok else "电台自检未通过 —— 发图会在 SESSION_BEGIN 卡到超时"))
    print("AT_QUICK2_DONE ok=%d" % (1 if ok else 0))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
