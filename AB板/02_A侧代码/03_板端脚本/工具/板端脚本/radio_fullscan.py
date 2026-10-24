#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""电台彻底体检：判断到底是"配置丢了"还是"根本不通"。

三层排查：
  A) 静默监听 —— 电台开机/心跳会不会主动吐字节？（每个波特率听 3 秒）
     如果任何波特率下收到"自发"字节 => 电台活着，只是波特率/配置不对
     如果一个字节都没有           => 电台要么没在发，要么线断了
  B) 命令扫描 —— 波特率 × 行尾(\r\n / \r / \n) × 命令，看有没有任何回应
  C) 结论
"""
import os
import sys
import termios
import time

DEV = '/dev/ttyUSB0'
BAUDS = [115200, 9600, 38400, 57600, 19200, 4800, 230400, 57600]
BMAP = {4800: termios.B4800, 9600: termios.B9600, 19200: termios.B19200,
        38400: termios.B38400, 57600: termios.B57600, 115200: termios.B115200,
        230400: termios.B230400}


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


def listen(fd, secs):
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


any_spontaneous = {}
any_reply = {}
seen_baud = set()

print('=' * 74)
print('A) 静默监听：电台会不会主动吐字节？（听 4 秒/波特率）')
print('=' * 74)
for b in dict.fromkeys(BAUDS):
    fd = open_at(b)
    r = listen(fd, 4.0)
    os.close(fd)
    mark = '' if not r else '  <<<< 收到字节！'
    print('  %6d baud : %3d 字节 %r%s' % (b, len(r), r[:40], mark))
    if r:
        any_spontaneous[b] = r
        seen_baud.add(b)

print()
print('=' * 74)
print('B) 命令扫描：波特率 x 行尾 x 命令')
print('=' * 74)
TERMS = [b'\r\n', b'\r', b'\n']
CMDS = [b'AT', b'AT+EXIT=1', b'AT+FREQ?', b'+++']
cands = sorted(seen_baud) if seen_baud else list(dict.fromkeys(BAUDS))
for b in cands:
    fd = open_at(b)
    listen(fd, 0.3)
    got_any = b''
    for t in TERMS:
        for c in CMDS:
            os.write(fd, c + t)
            r = listen(fd, 1.0)
            if r:
                got_any += r
                print('  [%6d] %-12r + %-6r -> %r' % (b, c, t, r[:50]))
            time.sleep(0.15)
    os.close(fd)
    if got_any:
        any_reply[b] = got_any

print()
print('=' * 74)
print('C) 结论')
print('=' * 74)
if any_reply:
    print('  ✅ **有回应！** 能通的波特率: %s' % sorted(any_reply))
    print('     => 电台是活的，只是之前波特率/行尾不对。用能通的那个重设即可。')
    sys.exit(0)
elif any_spontaneous:
    print('  ⚠️ **电台在主动发字节**（波特率 %s）=> 电台活着，但命令没被识别' % sorted(any_spontaneous))
    print('     => 试: 用那个波特率发 AT+EXIT=1，或检查电台是不是被设成了"纯透传/数传"模式')
    sys.exit(1)
else:
    print('  ❌ **一个字节都没收到过**（8 个波特率 × 4 秒静默监听 + 12 组命令扫描）')
    print()
    print('     这个结果指向【串口链路本身不通】或【电台没上电】，而不是"配置不对"：')
    print('       1. 电台的电源指示灯亮不亮？（亮=有电）')
    print('       2. CH340 到电台的杜邦线：TX/RX 有没有插反或松动？GND 接了没有？')
    print('       3. 电台天线接上没有？（没天线不影响串口，但影响收发）')
    print('       4. 换一根 USB 线 / 换一个 USB 口试试')
    print('       5. 如果之前跑得好好的、只是这次卡死 —— 有可能是电台进了某种')
    print('          需要"长按按键"或"特定时序"才能退出的状态，查一下电台手册的重置方式')
    sys.exit(2)
