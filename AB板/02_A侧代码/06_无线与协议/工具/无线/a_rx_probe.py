#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a_rx_probe.py —— GLC 2026-10-07：A 板当**接收端**做链路反测

目的：把"A→B 失败"拆成"RF 链路通不通"和"B 端听没听"两件事。
做法：A 板电台进透传后**纯监听**，把收到的任何字节打出来（hex + 可打印）。
      B 端只要在透传模式下发几个字符，我们这边就能看到 ⇒ 说明空口和双方电台都正常，
      问题就落在"B 端监听状态/脚本"上。
      如果 B 发了我这边什么都没有 ⇒ 天线/频点/速率/距离 有问题。

用法（板子上）：
    python3 /root/a_rx_probe.py 600          # 监听 600 秒
"""
import os
import sys
import termios
import time

DEV = '/dev/ttyUSB0'
BAUDMAP = {9600: termios.B9600, 115200: termios.B115200}


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
    t0 = time.time()
    out = b''
    while time.time() - t0 < secs:
        try:
            c = os.read(fd, 512)
        except (BlockingIOError, OSError):
            c = b''
        if c:
            out += c
        time.sleep(0.03)
    return out


def at(fd, cmd, wait=0.9):
    os.write(fd, (cmd + '\r\n').encode())
    return drain(fd, wait)


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 600.0
    if not os.path.exists(DEV):
        print('找不到 %s' % DEV)
        sys.exit(2)
    fd = open_dev(115200)

    print('[rxA] 进 AT 并复核参数…')
    drain(fd, 0.8)
    at(fd, '+++', 1.2)
    for c in ('AT+FREQ?', 'AT+SYMBOL?', 'AT+UART?', 'AT+RSSI?'):
        print('   %-11s -> %s' % (c, at(fd, c, 0.9).decode('utf-8', 'replace').strip().replace('\n', ' ')[:110]))
    r = at(fd, 'AT+EXIT=1', 1.2).decode('utf-8', 'replace').strip()
    print('[rxA] AT+EXIT=1 -> %r  (OK 才说明进了透传)' % r)
    if 'OK' not in r:
        print('[rxA] 没进透传，退出')
        os.close(fd)
        sys.exit(3)

    print('[rxA] *** 开始监听 %.0f 秒 ***  （请让 B 端在透传模式下发几个字符）' % secs)
    t0 = time.time()
    total = 0
    while time.time() - t0 < secs:
        try:
            c = os.read(fd, 4096)
        except (BlockingIOError, OSError):
            c = b''
        if c:
            total += len(c)
            el = time.time() - t0
            pr = ''.join(chr(b) if 32 <= b < 127 else '.' for b in c)
            print('[rxA] +%7.2fs  收到 %3d B  hex=%s  txt=%r' % (el, len(c), c[:48].hex(), pr[:48]))
        time.sleep(0.02)
    print('[rxA] 监听结束，共收到 %d 字节' % total)

    print('[rxA] 回 AT 看 RSSI（收到过包的话 rssi 会明显高于 -128）')
    drain(fd, 0.6)
    at(fd, '+++', 1.2)
    print('   AT+RSSI? -> %s' % at(fd, 'AT+RSSI?', 0.9).decode('utf-8', 'replace').strip().replace('\n', ' '))
    os.close(fd)
    print('RXA_DONE total=%d' % total)


if __name__ == '__main__':
    main()
