#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A_send_multi.py —— GLC 2026-10-08：**一次 AT，连发多个容器**

为什么需要它：
  A_send_robust.py 每次都做一遍 AT 自检（+++ / 4 条查询 / AT+EXIT=1），实测占 13.5 s，
  而真正空口只花 0.58 s ⇒ **连发多张时，AT 自检是纯浪费**。
  本脚本只做一次 AT，之后每张容器只花"写帧 + 等 ACK"。

用法（板子上）：
    python3 /root/A_send_multi.py /root/photos_glc/p*.glc          # 按 shell 展开的顺序发
    python3 /root/A_send_multi.py --wait 8 f1.glc f2.glc f3.glc
    python3 /root/A_send_multi.py --continue-on-fail ...           # 失败也继续（默认首次失败即停）

⚠️ 半双工：跑之前必须确认 B 端在监听。
⚠️ B 端的 radio_rx.py 收满**一帧就 break** ⇒ 若 B 没做成循环，第二个包必然超时。
   本脚本默认"首次失败即停"，正好用来判定 B 是单帧还是循环。
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('glcs', nargs='+')
    ap.add_argument('--wait', type=float, default=8.0)
    ap.add_argument('--continue-on-fail', action='store_true')
    a = ap.parse_args()

    if not os.path.exists(DEV):
        print('[AM] 找不到 %s' % DEV)
        sys.exit(2)
    for g in a.glcs:
        if not os.path.exists(g):
            print('[AM] 找不到容器 %s' % g)
            sys.exit(4)

    print('[AM] 待发 %d 个容器：' % len(a.glcs))
    for g in a.glcs:
        d = open(g, 'rb').read()
        print('[AM]   %-34s %5d B  md5=%s' % (os.path.basename(g), len(d), hashlib.md5(d).hexdigest()))

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
        print('[AM] ❌ 参数不符，不发')
        os.close(fd)
        sys.exit(3)

    r = at(fd, 'AT+EXIT=1', 1.2).decode('utf-8', 'replace').strip()
    print('[AM] AT+EXIT=1 -> %r' % r)
    if 'OK' not in r:
        print('[AM] ❌ 没进透传')
        os.close(fd)
        sys.exit(6)
    time.sleep(0.5)
    print('[AM] AT 自检总耗时 %.2f s（一次性，后面每张不再重复）' % (time.time() - t_setup))

    results = []
    t_all = time.time()
    for idx, g in enumerate(a.glcs, 1):
        data = open(g, 'rb').read()
        md5 = hashlib.md5(data).hexdigest()
        sumv = sum(data) & 0xFF
        frame = MAGIC + bytes([idx & 0xFF]) + len(data).to_bytes(2, 'big') + data + bytes([sumv])
        t0 = time.time()
        os.write(fd, frame)
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
        dt = time.time() - t0
        good = (res == 'OK')
        results.append((idx, os.path.basename(g), len(data), md5, res or '超时', dt))
        print('[AM] [%d/%d] %-16s %4d B  %-9s  %.2f s  md5=%s'
              % (idx, len(a.glcs), os.path.basename(g), len(data), res or '等 ACK 超时', dt, md5))
        if not good and not a.continue_on_fail:
            print('[AM] 首次失败即停（B 端 radio_rx.py 收满一帧就退出 ⇒ 需重开监听）')
            break
        time.sleep(0.3)
    os.close(fd)

    print('=' * 62)
    print('[AM] 总耗时 %.2f s   成功 %d / %d'
          % (time.time() - t_all, sum(1 for r in results if r[4] == 'OK'), len(a.glcs)))
    print('[AM] 请把下面这几行发给 B 端核对：')
    for idx, name, ln, md5, res, dt in results:
        print('[AM]   %s  md5=%s  bytes=%d  %s' % (name, md5, ln, res))
    sys.exit(0)


if __name__ == '__main__':
    main()
