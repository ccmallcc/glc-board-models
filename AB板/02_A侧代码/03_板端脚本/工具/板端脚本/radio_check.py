#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""电台状态检查（**修正版 2026-09-23**）

## 上一版错在哪（重要，别再踩）

上一版直接发 `AT+FREQ?` 去探测，结果：
  · 电台在**透传模式**时，AT 命令被当【数据】发走 => 一个字节都不回
    => 被误判成"电台死了"，白断了两回电

本次实测澄清的语义（**与直觉相反，务必记住**）：

| 操作 | 真实语义 |
|---|---|
| `+++`（**带 \r\n**）| **退出透传** → 进入【命令行模式】，回 `OK` |
| `AT+EXIT=1` | **退出命令行** → 进入【透传模式】，回 `OK` ← 名字有歧义！ |
| `AT` / `AT+xxx` | 只有在【命令行模式】才会被解释 |
| 裸 `+++`（不带行尾）| **本模块不认**（实测 2 秒静默 + 裸 +++ = 无任何回应）|

⇒ 正确顺序永远是：**先 `+++`（带行尾）拉到命令行模式**，再问参数。

## 本脚本做什么

`+++` → 问三个参数 → **恢复原状**（默认再发 `AT+EXIT=1` 送回透传，避免改变电台状态）
"""
import os
import sys
import termios
import time

DEV = '/dev/ttyUSB0'
WANT = [('AT+FREQ?', '470.110'), ('AT+SYMBOL?', '19.2'), ('AT+UART?', '115200')]

# 默认把电台留在透传模式（发图脚本会自己重新设置，这样最不容易出错）
LEAVE_TRANSPARENT = os.environ.get('GLC_LEAVE_TRANSPARENT', '1') == '1'


def open_at(baud=115200):
    fd = os.open(DEV, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    a = termios.tcgetattr(fd)
    iflag, oflag, cflag, lflag, ispeed, ospeed, cc = a
    iflag = oflag = lflag = 0
    cflag = termios.CS8 | termios.CREAD | termios.CLOCAL
    cc[termios.VMIN] = 0
    cc[termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW,
                      [iflag, oflag, cflag, lflag, termios.B115200, termios.B115200, cc])
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


def at(fd, cmd, wait=1.2):
    os.write(fd, (cmd + '\r\n').encode())
    return drain(fd, wait)


if not os.path.exists(DEV):
    print('  !! 没有 %s —— USB 没插好？' % DEV)
    sys.exit(1)

fd = open_at()
drain(fd, 2.0)

print('  [1] 先 +++ 拉到命令行模式（★ 必须带行尾）')
r = at(fd, '+++', 1.5)
print('      +++ -> %r' % r[:40])
if b'OK' not in r:
    print('      (没回 OK —— 可能本来就在命令行模式，继续)')

print('  [2] 问参数')
ok = True
for cmd, want in WANT:
    got = b''
    for _ in range(3):
        got = at(fd, cmd, 1.5)
        if want.encode() in got:
            break
        time.sleep(0.3)
    hit = want.encode() in got
    ok = ok and hit
    print('      %-11s -> %-52r [%s]'
          % (cmd, got.replace(b'\r\n', b' ')[:52], 'OK' if hit else '不符'))

print('  [3] 收尾')
if LEAVE_TRANSPARENT:
    r = at(fd, 'AT+EXIT=1', 1.2)
    print('      AT+EXIT=1 -> %r   （已送回透传模式，与发图前的状态一致）' % r[:30])
else:
    print('      保持命令行模式（GLC_LEAVE_TRANSPARENT=0）')
os.close(fd)

if ok:
    print('  ==> ✅ 电台正常')
    sys.exit(0)
print('  ==> ❌ 参数不符 —— 检查电台配置或串口线')
sys.exit(2)
