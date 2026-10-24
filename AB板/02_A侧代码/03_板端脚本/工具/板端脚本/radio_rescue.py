#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""电台自救：把所有已知的"退出透传"办法都试一遍。

背景：做完 AT 自检并进透传后，重开串口发 AT+FREQ? 没有回应（符合透传预期），
      但随后 AT+EXIT=1 也不回应 —— 之后电台对任何 AT 命令都无响应，CH340 已重新枚举过。

尝试顺序：
  1) 每个波特率下：先 +++（前后各留 2 s 静默），再 AT+EXIT=1，再 AT+FREQ?
  2) 同一个波特率下重复 3 轮
  3) 最后再回 115200 确认
"""
import os
import termios
import time

DEV = '/dev/ttyUSB0'
BAUDS = [115200, 9600, 38400, 57600, 19200]
BMAP = {9600: termios.B9600, 19200: termios.B19200, 38400: termios.B38400,
        57600: termios.B57600, 115200: termios.B115200}


def open_at(baud):
    fd = os.open(DEV, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    a = termios.tcgetattr(fd)
    iflag, oflag, cflag, lflag, ispeed, ospeed, cc = a
    iflag = oflag = lflag = 0
    cflag = termios.CS8 | termios.CREAD | termios.CLOCAL
    cc[termios.VMIN] = 0
    cc[termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW,
                      [iflag, oflag, cflag, lflag, BMAP[baud], BMAP[baud], cc])
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
        except Exception:
            c = b''
        if c:
            out += c
        time.sleep(0.02)
    return out


def try_baud(baud):
    fd = open_at(baud)
    drain(fd, 0.3)
    for rnd in range(3):
        # 1) +++ 前后留静默
        time.sleep(2.0)
        os.write(fd, b'+++')
        time.sleep(2.0)
        r1 = drain(fd, 1.0)
        # 2) AT+EXIT=1
        os.write(fd, b'AT+EXIT=1\r\n')
        r2 = drain(fd, 1.5)
        # 3) 探测
        os.write(fd, b'AT+FREQ?\r\n')
        r3 = drain(fd, 1.5)
        print('    [%6d] 第%d轮  +++ -> %-14r  EXIT -> %-14r  FREQ? -> %r'
              % (baud, rnd + 1, r1[:12], r2[:12], r3[:40]))
        if b'FREQ' in r3:
            os.close(fd)
            return True
    os.close(fd)
    return False


print('  开始扫波特率（每个 3 轮）…')
for b in BAUDS:
    if try_baud(b):
        print('  ==> ✅ 在 %d baud 恢复了' % b)
        raise SystemExit(0)

print('  ==> ❌ 所有波特率都无响应 —— 电台需要**断电重启**')
print('      做法：拔掉电台的电源（或拔掉给电台供电的那个 USB），等 5 秒再插回，')
print('            然后跑一次 bash /root/at_only_probe.sh 确认它回来了。')
raise SystemExit(1)
