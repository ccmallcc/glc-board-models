#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rssi_now.py —— GLC 2026-10-07：发完之后立刻查一次 RSSI（B 端 Step 3 要求的那个数）

用法（板子上）：python3 /root/rssi_now.py
它会：+++ 进 AT（已在 AT 时不依赖 +++ 的返回）→ 读 RSSI/FREQ/SYMBOL → AT+EXIT=1 切回透传。
"""
import os
import sys
import termios
import time

DEV = '/dev/ttyUSB0'


def open_dev(baud=115200):
    fd = os.open(DEV, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    a = termios.tcgetattr(fd)
    iflag, oflag, cflag, lflag, ispeed, ospeed, cc = a
    iflag = oflag = lflag = 0
    cflag = termios.CS8 | termios.CREAD | termios.CLOCAL
    ispeed = ospeed = termios.B115200
    cc[termios.VMIN] = 0
    cc[termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, [iflag, oflag, cflag, lflag, ispeed, ospeed, cc])
    try:
        termios.tcflush(fd, termios.TCIOFLUSH)
    except Exception:
        pass
    return fd


def drain(fd, secs):
    t0 = time.time()
    out = b''
    while time.time() - t0 < secs:
        try:
            c = os.read(fd, 512)
        except (BlockingIOError, OSError):
            c = b''
        if c:
            out += c
        time.sleep(0.02)
    return out


def at(fd, cmd, wait=1.0):
    os.write(fd, (cmd + '\r\n').encode())
    return drain(fd, wait)


def at_retry(fd, cmd, want=None, tries=4, wait=1.0):
    got = ''
    for _ in range(tries):
        r = at(fd, cmd, wait).decode('utf-8', 'replace').strip()
        if r and (want is None or want in r):
            return r
        if len(r) > len(got):
            got = r
    return got


def main():
    if not os.path.exists(DEV):
        print('找不到 %s' % DEV)
        sys.exit(2)
    fd = open_dev()
    drain(fd, 1.5)
    r = at(fd, '+++', 1.5).decode('utf-8', 'replace').strip()
    print('+++ -> %r   (注意：已在 AT 模式时 +++ 可能不回 OK，这不代表失败)' % r)
    for cmd in ('AT+RSSI?', 'AT+FREQ?', 'AT+SYMBOL?', 'AT+ADDR?'):
        print('  %-11s -> %s' % (cmd, at_retry(fd, cmd).replace('\n', ' ')))
    # 不管前面怎样，无条件下发一次 AT+EXIT=1，把电台放回透传
    r = at(fd, 'AT+EXIT=1', 1.2).decode('utf-8', 'replace').strip()
    print('AT+EXIT=1 -> %r   (已切回透传)' % r)
    os.close(fd)
    print('RSSI_DONE')


if __name__ == '__main__':
    main()
