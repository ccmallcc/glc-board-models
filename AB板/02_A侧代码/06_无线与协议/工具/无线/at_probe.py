#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""at_probe.py —— GLC 2026-10-07 电台状态诊断（只读为主，最后一条会切透传）

目的：把 A_send.py 里**被丢掉的 AT 应答**打出来，特别是 `AT+EXIT=1` 到底回什么。
      A_send.py 里是 `at(fd, 'AT+EXIT=1', 0.8)` —— 返回值直接扔了，
      如果它其实回了 ERROR（电台没进透传），我们就会看到"发出去 330 B 但空口上什么都没发"。
"""
import os
import sys
import termios
import time

DEV = '/dev/ttyUSB0'
BAUDMAP = {9600: termios.B9600, 19200: termios.B19200, 115200: termios.B115200}

CMDS = [
    'AT+VER?', 'AT+FREQ?', 'AT+SYMBOL?', 'AT+UART?', 'AT+ADDR?', 'AT+RSSI?',
    'AT+PWR?', 'AT+NET?', 'AT+MODE?', 'AT+CH?', 'AT+SPD?', 'AT+EXIT?',
    'AT+HELP', 'AT+?', 'AT',
]


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
    if not os.path.exists(DEV):
        print('找不到 %s' % DEV)
        sys.exit(2)
    fd = open_dev(115200)

    print('--- 先空闲 0.8s，再发 +++ 进 AT ---')
    drain(fd, 0.8)
    r = at(fd, '+++', 1.2)
    print('  +++ 回显 = %r' % r.decode('utf-8', 'replace').strip()[:160])

    print('--- 逐条查询 ---')
    for c in CMDS:
        resp = at(fd, c, 0.9).decode('utf-8', 'replace').strip()
        print('  %-12s -> %s' % (c, resp[:150] if resp else '(无应答)'))

    print('--- 重点：AT+EXIT=1 的应答（A_send.py 把它扔了）---')
    r = at(fd, 'AT+EXIT=1', 1.2)
    print('  AT+EXIT=1 回显 = %r' % r.decode('utf-8', 'replace').strip()[:200])
    print('  (空 或 ERROR 都说明"没进透传")')

    print('--- 透传模式下写 64 B 测试数据，看电台是否回吐/回显 ---')
    time.sleep(0.5)
    os.write(fd, b'GLCPROBE' * 8)
    back = drain(fd, 2.0)
    print('  透传写入后读回 %d 字节: %r' % (len(back), back[:80]))

    print('--- 再 +++ 回 AT，确认电台还在 ---')
    drain(fd, 0.6)
    r = at(fd, '+++', 1.2)
    print('  +++ 回显 = %r' % r.decode('utf-8', 'replace').strip()[:160])
    r = at(fd, 'AT+FREQ?', 0.9)
    print('  AT+FREQ? = %r' % r.decode('utf-8', 'replace').strip()[:120])
    os.close(fd)
    print('PROBE_DONE')


if __name__ == '__main__':
    main()
