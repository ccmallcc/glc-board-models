#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A_send_robust.py —— GLC 2026-10-07：A 板发送（**加固版**）

相对队友 A_send.py 的两处修补（帧格式/AT 参数/判据完全不变）：

 ① **AT 应答读取带重试**
    A_send.py 用固定 drain 窗口读 AT 应答。实测（2026-10-07 21:58）出现过
    `AT+UART?` 只读到尾巴 `"top:1, check:None"`（丢了前半段），
    于是误判"参数不一致"直接退出、根本没发。原因是上一条命令的应答迟到，
    被下一条命令的窗口读走/截断。
    这里改成：每条命令最多读 3 次，任一次里出现期望子串就算通过。

 ② **等 ACK 时把收到的原始字节打出来**
    A_send.py 只报"等 ACK 超时"，看不出对端到底有没有回东西。
    这里把 ACK 窗口内收到的每个字节按 hex 打印 —— 用来区分：
      · 收到 `aa5506`            -> 成功
      · 收到 `aa5515`            -> 对端校验失败（数据被空口弄坏了）
      · 收到别的字节             -> 对端在说话但协议不对
      · **一个字节都没有**        -> 空口/B 端监听状态问题（和"A 侧发得对不对"无关）

用法（板子上）：
    python3 /root/A_send_robust.py                       # 默认容器，3 次重发
    python3 /root/A_send_robust.py --wait 10             # 等 ACK 10 秒
"""
import argparse
import hashlib
import os
import sys
import termios
import time

DEV = '/dev/ttyUSB0'
MAGIC = b'\xAA\x55'
BAUDMAP = {9600: termios.B9600, 19200: termios.B19200, 115200: termios.B115200}
WANT = (('AT+FREQ?', '470.110'), ('AT+SYMBOL?', '19.2'), ('AT+UART?', '115200'))


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
        time.sleep(0.02)
    return out


def at(fd, cmd, wait=0.9):
    os.write(fd, (cmd + '\r\n').encode())
    return drain(fd, wait)


def at_retry(fd, cmd, want=None, tries=3, wait=1.0):
    """读 AT 应答；若给了 want，读到含 want 的应答为止（最多 tries 次）。"""
    got = ''
    for k in range(tries):
        r = at(fd, cmd, wait).decode('utf-8', 'replace').strip()
        if r and (want is None or want in r):
            return r, k + 1
        if len(r) > len(got):
            got = r
    return got, tries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('container', nargs='?', default='/root/glc/pack/full_img0.glc')
    ap.add_argument('--retry', type=int, default=3)
    ap.add_argument('--wait', type=float, default=8.0)
    a = ap.parse_args()

    if not os.path.exists(DEV):
        print('[AR] 找不到 %s' % DEV)
        sys.exit(2)
    if not os.path.exists(a.container):
        print('[AR] 找不到容器 %s' % a.container)
        sys.exit(4)

    data = open(a.container, 'rb').read()
    md5 = hashlib.md5(data).hexdigest()
    sumv = sum(data) & 0xFF
    frame = MAGIC + bytes([1]) + len(data).to_bytes(2, 'big') + data + bytes([sumv])
    print('[AR] 容器 %s  %d B  md5=%s' % (a.container, len(data), md5))
    print('[AR] 帧长 %d B（= 5 + payload + 1 校验）' % len(frame))

    fd = open_dev(115200)
    print('[AR] 清空串口缓冲（2.0 s）…')
    drain(fd, 2.0)
    print('[AR] 发 +++ 进 AT…')
    r = at(fd, '+++', 1.5).decode('utf-8', 'replace').strip()
    print('[AR]   +++ -> %r' % r)
    if 'OK' not in r:
        print('[AR] +++ 没有回 OK，再试一次')
        drain(fd, 0.8)
        r = at(fd, '+++', 1.5).decode('utf-8', 'replace').strip()
        print('[AR]   +++ -> %r' % r)

    print('[AR] 版本: %s' % at_retry(fd, 'AT+VER?', 'TP5603')[0].replace('\n', ' '))
    ok = True
    for cmd, want in WANT:
        resp, tries = at_retry(fd, cmd, want, tries=3, wait=1.0)
        hit = want in resp
        ok = ok and hit
        print('[AR]   %-11s -> %-52s [读了%d次, %s]' %
              (cmd, resp.replace('\n', ' ')[:52], tries, 'OK' if hit else '不符'))
    print('[AR]   AT+ADDR?    -> %s' % at_retry(fd, 'AT+ADDR?')[0].replace('\n', ' '))
    print('[AR]   AT+PWR?     -> %s' % at_retry(fd, 'AT+PWR?')[0].replace('\n', ' '))
    print('[AR]   AT+RSSI?    -> %s' % at_retry(fd, 'AT+RSSI?')[0].replace('\n', ' '))
    if not ok:
        print('[AR] ❌ 参数确有不符（已重试 3 次仍读不到期望值）。先别发。')
        os.close(fd)
        sys.exit(3)
    print('[AR] ✅ 参数与 B 端要求一致（470.110MHz / 19.2kbps / 115200）')

    r = at(fd, 'AT+EXIT=1', 1.2).decode('utf-8', 'replace').strip()
    print('[AR] AT+EXIT=1 -> %r' % r)
    if 'OK' not in r:
        print('[AR] ❌ 没进透传，发送无意义，退出')
        os.close(fd)
        sys.exit(6)
    print('[AR] 已切到透传模式（等 0.5 s 让电台切换完）')
    time.sleep(0.5)

    done = False
    for k in range(1, a.retry + 1):
        n = os.write(fd, frame)
        print('[AR] 第 %d 次：已写 %d B 到串口，开始等 ACK（%.1f s，期间打印所有收到的原始字节）'
              % (k, n, a.wait))
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
                pr = ''.join(chr(b) if 32 <= b < 127 else '.' for b in c)
                print('[AR]   +%.2fs 收到 %d B  hex=%s  txt=%r'
                      % (time.time() - t0, len(c), c[:32].hex(), pr[:32]))
            i = buf.find(MAGIC)
            if i >= 0 and len(buf) >= i + 3:
                st = buf[i + 2]
                res = 'OK' if st == 0x06 else ('NAK(校验失败)' if st == 0x15 else 'OTHER(0x%02x)' % st)
                break
            time.sleep(0.02)
        if res == 'OK':
            print('[AR] 第 %d 次发送 -> 收到 ACK OK ✅  传输成功' % k)
            done = True
            break
        print('[AR] 第 %d 次发送 -> %s（本次共收到 %d B）'
              % (k, res or '等 ACK 超时', len(buf)))
        time.sleep(0.5)
    os.close(fd)

    print('=' * 56)
    print('[AR] 结果：%s' % ('成功 ✅' if done else '失败 ❌'))
    print('[AR] 请把这行发给 B 端核对： md5=%s  bytes=%d' % (md5, len(data)))
    sys.exit(0 if done else 5)


if __name__ == '__main__':
    main()
