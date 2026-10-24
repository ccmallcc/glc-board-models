#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A_send_multi2.py —— GLC 2026-10-08：一次 AT + **持久重试**连发多个容器

为什么需要"持久重试"（实测教训）：
  B 端的 radio_rx.py **收满一帧就 break 退出**（rx_listen.sh 只是 nohup 起它一次），
  ⇒ 目标端每开一次监听只吃一帧。实测：连发时第 1 帧 0.58 s ACK 成功，第 2 帧必超时。
  若发送端"发一次、等不到就放弃"，就得人工来回 7 轮。
  本脚本改成：**对每个容器反复重发，直到收到 ACK 才推进到下一个**，中间留 gap 让对方重启监听。
  ⇒ 发送端一次挂上就能把全部推完，对方只要照着节奏重启。

用法（板子上）：
    python3 /root/A_send_multi2.py <glc1> <glc2> ...
    python3 /root/A_send_multi2.py --wait 5 --gap 5 --attempts 40 /root/photos_glc/p*.glc
    python3 /root/A_send_multi2.py --no-retry ...      # 每帧只发一次（旧行为）

⚠️ 半双工：跑之前必须确认目标端在监听。
⚠️ 脚本运行期间**电台一直被占着**（在透传模式），别同时跑别的电台脚本。
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


def at(fd, cmd, wait=1.0):
    os.write(fd, (cmd + '\r\n').encode())
    return drain(fd, wait)


def at_retry(fd, cmd, want=None, tries=3, wait=1.0):
    got = ''
    for _ in range(tries):
        r = at(fd, cmd, wait).decode('utf-8', 'replace').strip()
        if r and (want is None or want in r):
            return r
        if len(r) > len(got):
            got = r
    return got


def send_once(fd, frame, wait):
    t0 = time.time()
    os.write(fd, frame)
    buf = b''
    res = None
    while time.time() - t0 < wait:
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
    return (res, time.time() - t0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('glcs', nargs='+')
    ap.add_argument('--wait', type=float, default=5.0, help='每次等 ACK 的秒数')
    ap.add_argument('--gap', type=float, default=5.0, help='失败后隔多久重试')
    ap.add_argument('--attempts', type=int, default=40, help='每个容器最多重试几次')
    ap.add_argument('--no-retry', action='store_true', help='每帧只发一次')
    a = ap.parse_args()

    if not os.path.exists(DEV):
        print('[AM] 找不到 %s' % DEV)
        sys.exit(2)
    for g in a.glcs:
        if not os.path.exists(g):
            print('[AM] 找不到容器 %s' % g)
            sys.exit(4)
    attempts = 1 if a.no_retry else a.attempts

    print('[AM] 待发 %d 个容器：' % len(a.glcs))
    for g in a.glcs:
        d = open(g, 'rb').read()
        print('[AM]   %-16s %5d B  md5=%s' % (os.path.basename(g), len(d), hashlib.md5(d).hexdigest()))
    print('[AM] 策略：每容器最多 %d 次，每次等 %g s，失败隔 %g s（单容器最坏 %.1f min）'
          % (attempts, a.wait, a.gap, attempts * (a.wait + a.gap) / 60.0))

    fd = open_dev(115200)
    t_setup = time.time()
    print('[AM] 清缓冲 2.0 s …')
    drain(fd, 2.0)
    r = at(fd, '+++', 1.5).decode('utf-8', 'replace').strip()
    print('[AM]   +++ -> %r' % r)
    ok = True
    for cmd, want in WANT:
        resp = at_retry(fd, cmd, want, tries=3)
        hit = want in resp
        ok = ok and hit
        print('[AM]   %-11s -> %-48s [%s]' % (cmd, resp.replace('\n', ' ')[:48], 'OK' if hit else '不符'))
    if not ok:
        print('[AM] 参数不符，不发')
        os.close(fd)
        sys.exit(3)
    r = at(fd, 'AT+EXIT=1', 1.2).decode('utf-8', 'replace').strip()
    print('[AM] AT+EXIT=1 -> %r' % r)
    if 'OK' not in r:
        print('[AM] 没进透传')
        os.close(fd)
        sys.exit(6)
    time.sleep(0.5)
    print('[AM] AT 自检一次性耗时 %.2f s' % (time.time() - t_setup))
    print('[AM] === 开始发送（B 端按需重启监听）===')
    sys.stdout.flush()

    done, failed = [], []
    t_all = time.time()
    for idx, g in enumerate(a.glcs, 1):
        data = open(g, 'rb').read()
        md5 = hashlib.md5(data).hexdigest()
        sumv = sum(data) & 0xFF
        frame = MAGIC + bytes([idx & 0xFF]) + len(data).to_bytes(2, 'big') + data + bytes([sumv])
        name = os.path.basename(g)
        got = False
        for k in range(1, attempts + 1):
            res, dt = send_once(fd, frame, a.wait)
            if res == 'OK':
                print('[AM] [%d/%d] %-16s %4d B  OK  %.2f s  (第 %d 次尝试)  md5=%s'
                      % (idx, len(a.glcs), name, len(data), dt, k, md5))
                sys.stdout.flush()
                done.append((name, len(data), md5))
                got = True
                break
            print('[AM] [%d/%d] %-16s 第 %d/%d 次：%s (%.2f s) -- 隔 %g s 重试'
                  % (idx, len(a.glcs), name, k, attempts, res or '等 ACK 超时', dt, a.gap))
            sys.stdout.flush()
            time.sleep(a.gap)
        if not got:
            print('[AM] [%d/%d] %-16s %d 次都没成功，跳过' % (idx, len(a.glcs), name, attempts))
            failed.append(name)
        time.sleep(0.3)
    os.close(fd)

    print('=' * 66)
    print('[AM] 总耗时 %.1f s   成功 %d   失败 %d' % (time.time() - t_all, len(done), len(failed)))
    print('[AM] 请把下面这些行发给 B 端核对：')
    for name, ln, md5 in done:
        print('[AM]   %-16s md5=%s  bytes=%d' % (name, md5, ln))
    if failed:
        print('[AM] 未成功：%s' % ' '.join(failed))
    print('[AM] SEND_MULTI2_DONE')
    sys.exit(0)


if __name__ == '__main__':
    main()
