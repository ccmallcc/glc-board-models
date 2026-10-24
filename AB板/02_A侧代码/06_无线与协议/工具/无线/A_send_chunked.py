#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A_send_chunked.py —— GLC 2026-10-07 备用发送（分块节流版）

为什么有这个文件：
  队友的 A_send.py 是 `os.write(fd, frame)` **一次性把 330 B 全写进串口**。
  我们在 2026-10-06 的实测里踩过相反的经验：
    「电台自身 UART 接收缓冲很小，一次性写 300+ 字节会灌爆 ⇒ 收到 3 帧但每帧只剩 68 B」，
    当时的解法是 **32 B/块 + 200 B/s 节流**。
  新版电台固件（V1.0.6_T231226）可能已经改善，而且新版协议带 ACK + 自动重发 3 次，
  所以先按队友的 A_send.py 走。
  **只有在 A_send.py 连续 3 次「等 ACK 超时」时才用本脚本**作为对照实验 ——
  其余一切（帧格式、AT 参数、判据）与 A_send.py **完全相同**，唯一区别是发送时分块。

用法（板子上）：
    python3 /root/A_send_chunked.py                          # 32 B/块, 200 B/s
    python3 /root/A_send_chunked.py --chunk 16 --rate 150    # 更保守
    python3 /root/A_send_chunked.py --chunk 0                # 0 = 不分块（等价 A_send.py）

⚠️ 半双工：跑之前必须确认 B 端已在监听。
"""
import argparse
import hashlib
import os
import sys
import termios
import time

DEV = '/dev/ttyUSB0'
MAGIC = b'\xAA\x55'
BAUDMAP = {9600: termios.B9600, 19200: termios.B19200, 38400: termios.B38400,
           57600: termios.B57600, 115200: termios.B115200}


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
    return drain(fd, wait).decode('utf-8', 'replace')


def send_chunked(fd, frame, chunk, rate):
    """分块写；每块后 sleep(块长/速率) 做节流。chunk<=0 表示不分块。"""
    if chunk <= 0:
        os.write(fd, frame)
        return 1
    n = 0
    off = 0
    while off < len(frame):
        blk = frame[off:off + chunk]
        os.write(fd, blk)
        off += len(blk)
        n += 1
        time.sleep(len(blk) / float(rate))
    # 补足整帧应占的空口时间，避免 B 端还没收完我们就开始等
    need = len(frame) / float(rate)
    time.sleep(max(0.0, need * 0.2))
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('container', nargs='?', default='/root/glc/pack/full_img0.glc')
    ap.add_argument('--chunk', type=int, default=32)
    ap.add_argument('--rate', type=float, default=200.0)
    ap.add_argument('--retry', type=int, default=3)
    ap.add_argument('--wait', type=float, default=8.0)
    a = ap.parse_args()

    if not os.path.exists(DEV):
        print('[A2] 找不到 %s' % DEV)
        sys.exit(2)
    if not os.path.exists(a.container):
        print('[A2] 找不到容器: %s' % a.container)
        sys.exit(4)

    data = open(a.container, 'rb').read()
    md5 = hashlib.md5(data).hexdigest()
    sumv = sum(data) & 0xFF
    frame = MAGIC + bytes([1]) + len(data).to_bytes(2, 'big') + data + bytes([sumv])
    print('[A2] 容器 %s  %d B  md5=%s' % (a.container, len(data), md5))
    print('[A2] 帧长 %d B；分块 = %s，速率 = %s B/s' %
          (len(frame), ('不分块' if a.chunk <= 0 else '%d B' % a.chunk), a.rate))

    fd = open_dev(115200)
    drain(fd, 0.6)                       # 先空闲 0.6s 再进 AT（旧固件要求）
    at(fd, '+++', 1.0)
    freq = at(fd, 'AT+FREQ?')
    symb = at(fd, 'AT+SYMBOL?')
    print('[A2] FREQ?   %s' % freq.strip().replace('\n', ' '))
    print('[A2] SYMBOL? %s' % symb.strip().replace('\n', ' '))
    if ('470.110' not in freq) or ('19.2' not in symb):
        print('[A2] ⚠️ 电台参数与 B 端不一致，先别发。请跑 A_send.py --check-only')
        os.close(fd)
        sys.exit(3)
    at(fd, 'AT+EXIT=1', 0.8)
    print('[A2] 已切到透传模式')

    ok = False
    for k in range(1, a.retry + 1):
        nblk = send_chunked(fd, frame, a.chunk, a.rate)
        print('[A2] 第 %d 次：已发 %d 块，开始等 ACK（%.1fs）' % (k, nblk, a.wait))
        t0 = time.time()
        buf = b''
        res = None
        while time.time() - t0 < a.wait:
            try:
                c = os.read(fd, 256)
            except (BlockingIOError, OSError):
                c = b''
            if c:
                buf += c
            i = buf.find(MAGIC)
            if i >= 0 and len(buf) >= i + 3:
                st = buf[i + 2]
                res = 'OK' if st == 0x06 else ('NAK' if st == 0x15 else 'OTHER(0x%02x)' % st)
                break
            time.sleep(0.02)
        if res == 'OK':
            print('[A2] 第 %d 次发送 -> 收到 ACK OK ✅  传输成功' % k)
            ok = True
            break
        print('[A2] 第 %d 次发送 -> %s，重发' % (k, res or '等 ACK 超时'))
        time.sleep(0.5)
    os.close(fd)

    print('=' * 56)
    print('[A2] 结果：%s' % ('成功 ✅' if ok else '失败 ❌'))
    print('[A2] 请把这行发给 B 端核对： md5=%s  bytes=%d' % (md5, len(data)))
    sys.exit(0 if ok else 5)


if __name__ == '__main__':
    main()
