#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""radio_rx_session.py —— GLC 电台**会话模式**接收端 v2【给 B 板用的参考实现】
（GLC 2026-10-09，A 端编写）

为什么要有它
------------
原来的 `radio_rx.py` 是「**收满一帧就 break**」，所以 A 每发一张，你都要人工重启一次监听。
实测 7 张那批：**总耗时 368 s，其中真正空口只占 4.8 s**，其余 363 s 全在等人重启。
本脚本支持 A 端发来的「**我要发 N 张**」控制帧，**一次开监听就能把 N 张全收完**。

v2 相比 v1 的改动（针对"N 可能到 63"）
------------------------------------
  · **BEGIN 的长度段变成可选**（A 端可能不列长度，那时就不做长度校验）
  · **会话循环不再靠"数够 N 帧"结束，而是收到 SESSION_END / ABORT / 空闲超时才结束**
    —— 这样 A 端的**补发**（SESSION_RETRY）能自然地插进来，不会因为"数满了"而漏收
  · 支持 `0x13 SESSION_RETRY`：A 说"这几张我没收到"，它们会随后再来，照收即可
  · 收完打印**收到哪些 / 缺哪些**，一目了然

协议（见 40 号文档）
--------------------
统一信封（**数据帧格式一个字节都没改**）：
    AA 55 | SEQ(1B) | LEN(2B 大端) | PAYLOAD | SUM(payload)&0xFF
      SEQ = 0x00        控制帧
      SEQ = 0x01..0xFE  数据帧（图片序号，从 1 开始）
应答：AA 55 06 = ACK ；AA 55 15 = NAK

控制帧（SEQ=0x00，PAYLOAD 第一个字节是 CMD）：
    0x10 SESSION_BEGIN  CMD | N | MODE | RATE | [LEN_0..LEN_{N-1}]   ← 长度段可选
    0x11 SESSION_END    CMD | SENT | OK
    0x12 SESSION_ABORT  CMD | REASON
    0x13 SESSION_RETRY  CMD | K | seq_1..seq_K

顺带修掉两个已知坑
------------------
1. **电台卡在 AT 模式**（上次排查很久的根因）：`open_dev()` 之后必须发
   `AT+EXIT=1` 并**检查它的返回值**。注意：**已经是透传模式时再发 `+++` 不会回 OK**，
   所以不能靠 `+++` 是否回 OK 来判断状态。
2. 收帧依赖"一次 read 拿到整帧"是不安全的 —— 本脚本用缓冲区切帧，**分片到达也能正确还原**。

用法（B 板上）
--------------
    # 等 A 端的 SESSION_BEGIN，然后把本次要发的全部收完（推荐）
    python3 /root/radio_rx_session.py -d /root/glc/pack/rxs

    # 收完自动解码（一张约 57 s，63 张要一小时 —— 演示时建议只解几张）
    python3 /root/radio_rx_session.py -d /root/glc/pack/rxs --decode
"""
import argparse
import hashlib
import os
import sys
import termios
import time

DEV = os.environ.get('GLC_RADIO_DEV', '/dev/ttyUSB0')   # 可用环境变量覆盖，便于用 PTY 做集成测试
MAGIC = b'\xAA\x55'
BAUDMAP = {9600: termios.B9600, 19200: termios.B19200, 115200: termios.B115200}

CMD_BEGIN = 0x10
CMD_END = 0x11
CMD_ABORT = 0x12
CMD_RETRY = 0x13
ACK = 0x06
NAK = 0x15


# ----------------------------------------------------------------- 串口
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


def enter_transparent(fd):
    """★ 关键：让电台进入透传模式。

    实测教训：**已经是透传模式时，再发 `+++` 不会回 OK**。
    所以不能靠 `+++` 的返回值判断状态，必须**无条件发 `AT+EXIT=1` 并检查它**。
    """
    drain(fd, 1.5)
    os.write(fd, b'+++')
    r1 = drain(fd, 1.5)
    os.write(fd, b'AT+EXIT=1\r\n')
    r2 = drain(fd, 1.5)
    ok = b'OK' in r2
    print('[RX] +++ -> %r' % r1.decode('utf-8', 'replace').strip())
    print('[RX] AT+EXIT=1 -> %r   %s'
          % (r2.decode('utf-8', 'replace').strip(), '✅ 已进透传' if ok else '❌ 没进透传！'))
    return ok


def send_ack(fd, nak=False):
    os.write(fd, MAGIC + bytes([NAK if nak else ACK]))


# ----------------------------------------------------------------- 收帧
class Reader(object):
    """从串口流里切出完整帧（分片到达也能还原）。"""

    def __init__(self, fd):
        self.fd = fd
        self.buf = b''

    def _fill(self):
        try:
            c = os.read(self.fd, 512)
        except (BlockingIOError, OSError):
            c = b''
        if c:
            self.buf += c
        return bool(c)

    def next_frame(self, timeout):
        """返回 (seq, payload, 说明) 或 (None, None, 原因)。"""
        t0 = time.time()
        while time.time() - t0 < timeout:
            self._fill()
            i = self.buf.find(MAGIC)
            if i < 0:
                if len(self.buf) > 1:
                    self.buf = b'\xAA' if self.buf[-1:] == b'\xAA' else b''
                time.sleep(0.02)
                continue
            if i > 0:
                self.buf = self.buf[i:]
            if len(self.buf) < 5:
                time.sleep(0.02)
                continue
            seq = self.buf[2]
            ln = (self.buf[3] << 8) | self.buf[4]
            need = 5 + ln + 1
            if len(self.buf) < need:
                if ln > 4096:                    # 长度荒谬 ⇒ 当噪声，丢一个字节重找
                    self.buf = self.buf[2:]
                    continue
                time.sleep(0.02)
                continue
            payload = self.buf[5:5 + ln]
            summ = self.buf[5 + ln]
            self.buf = self.buf[need:]
            if (sum(payload) & 0xFF) != summ:
                return (None, None, '校验和不符 (算出 0x%02X, 帧里 0x%02X)'
                        % (sum(payload) & 0xFF, summ))
            return (seq, payload, None)
        return (None, None, '%.1f s 内没有完整帧' % timeout)


def parse_begin(payload):
    """返回 (n, mode, rate, lens_or_None)"""
    n = payload[1] if len(payload) > 1 else 0
    mode = payload[2] if len(payload) > 2 else 0
    rate = payload[3] if len(payload) > 3 else 0
    lens = None
    if len(payload) >= 4 + 2 * n:                # 长度段可选：够长才解析
        lens = []
        for k in range(n):
            o = 4 + 2 * k
            lens.append((payload[o] << 8) | payload[o + 1])
    return n, mode, rate, lens


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-d', '--dir', default='/root/glc/pack/rxs', help='保存目录')
    ap.add_argument('-t', '--timeout', type=float, default=180.0,
                    help='等第一个 BEGIN 的超时（秒），默认 180')
    ap.add_argument('--idle-timeout', type=float, default=60.0,
                    help='会话中"多久没帧就收摊"（秒），默认 60')
    ap.add_argument('--decode', action='store_true', help='收完后调用板端解码')
    a = ap.parse_args()

    if not os.path.exists(DEV):
        print('[RX] 找不到 %s' % DEV)
        sys.exit(2)
    if not os.path.isdir(a.dir):
        os.makedirs(a.dir)

    fd = open_dev(115200)
    if not enter_transparent(fd):
        print('[RX] 没进透传模式，退出。请检查电台（重新上电 / AT+EXIT=1）')
        os.close(fd)
        sys.exit(6)

    rd = Reader(fd)
    print('=' * 68)
    print('[RX] 等 A 端的 SESSION_BEGIN（最多 %.0f s）…' % a.timeout)
    print('[RX]   迟迟不来就确认：A 端已启动、频率/速率一致')
    print('=' * 68)
    sys.stdout.flush()

    n_expect = 0
    lens = None
    expected = set()
    got = {}
    results = []

    # ---------------- 等 BEGIN ----------------
    t0 = time.time()
    while time.time() - t0 < a.timeout:
        seq, payload, why = rd.next_frame(min(10.0, max(1.0, a.timeout)))
        if seq is None:
            if why and '校验和' in why:
                print('[RX] %s -> 回 NAK' % why)
                send_ack(fd, nak=True)
            continue
        if seq != 0:
            print('[RX] ⚠️ 没等到 SESSION_BEGIN，却收到数据帧 seq=%d（%d B）—— 按旧式单帧处理'
                  % (seq, len(payload)))
            fn = os.path.join(a.dir, 'rx%d.glc' % seq)
            with open(fn, 'wb') as f:
                f.write(payload)
            send_ack(fd)
            m = hashlib.md5(payload).hexdigest()
            print('[RX]   -> %s  %d B  md5=%s' % (fn, len(payload), m))
            print('[RX]    （若希望一次收多张，请让 A 端用 A_send_session.py）')
            os.close(fd)
            print('[RX] RX_SESSION_DONE  got=1/1')
            return
        cmd = payload[0] if payload else -1
        if cmd == CMD_BEGIN:
            n_expect, mode, rate, lens = parse_begin(payload)
            expected = set(range(1, n_expect + 1))
            send_ack(fd)
            print('[RX] ✅ SESSION_BEGIN：本次要收 **%d 张**  mode=%d rate=%d' % (n_expect, mode, rate))
            if lens:
                print('[RX]    逐张长度 = %s' % lens)
            else:
                print('[RX]    （A 端没列长度，本次不做长度校验）')
            print('[RX]    已回 ACK —— 接下来连收，**不用再人工重启**；收到 SESSION_END 为止')
            sys.stdout.flush()
            break
        if cmd == CMD_ABORT:
            send_ack(fd)
            print('[RX] A 端中止会话（reason=%d）' % (payload[1] if len(payload) > 1 else -1))
            os.close(fd)
            return
        print('[RX] 收到未知控制帧 CMD=0x%02X，忽略' % cmd)

    if not expected:
        print('[RX] ❌ 超时，没收到 BEGIN。退出。')
        os.close(fd)
        sys.exit(1)

    # ---------------- 会话循环：收到 END/ABORT/空闲超时才结束 ----------------
    #   ★ 不靠"数够 N 帧"结束 —— 这样 A 端的补发(SESSION_RETRY)能自然插进来
    t_sess = time.time()
    ended = False
    while not ended:
        seq, payload, why = rd.next_frame(a.idle_timeout)
        if seq is None:
            if why and '校验和' in why:
                print('[RX]   %s -> 回 NAK' % why)
                send_ack(fd, nak=True)
                continue
            print('[RX] ⏰ 空闲 %.0f s 没收到帧，收摊' % a.idle_timeout)
            break
        if seq == 0:
            cmd = payload[0] if payload else -1
            if cmd == CMD_END:
                send_ack(fd)
                print('[RX] SESSION_END：对方报告 sent=%d ok=%d'
                      % (payload[1] if len(payload) > 1 else -1,
                         payload[2] if len(payload) > 2 else -1))
                ended = True
            elif cmd == CMD_ABORT:
                send_ack(fd)
                print('[RX] A 端中止会话（reason=%d）'
                      % (payload[1] if len(payload) > 1 else -1))
                ended = True
            elif cmd == CMD_RETRY:
                k = payload[1] if len(payload) > 1 else 0
                seqs = list(payload[2:2 + k])
                expected |= set(seqs)
                send_ack(fd)
                print('[RX] SESSION_RETRY：对方要补发 %d 张 -> %s（等着收）' % (k, seqs))
            elif cmd == CMD_BEGIN:
                n2, _, _, lens2 = parse_begin(payload)
                send_ack(fd)
                print('[RX] 又收到 SESSION_BEGIN（N=%d）—— 按新会话继续收' % n2)
                n_expect, lens = n2, lens2
                expected |= set(range(1, n2 + 1))
            else:
                print('[RX] 会话中收到未知控制帧 0x%02X，忽略' % cmd)
            sys.stdout.flush()
            continue

        # ---- 数据帧：验长度（若有）→ 存盘 → ACK ----
        exp = lens[seq - 1] if (lens and 1 <= seq <= len(lens)) else None
        if exp is not None and exp != len(payload):
            print('[RX]   seq=%-3d ⚠️ 长度不符：收到 %d B，BEGIN 里说 %d B —— 仍然存下并 ACK'
                  % (seq, len(payload), exp))
        fn = os.path.join(a.dir, 'rx%d.glc' % seq)
        with open(fn, 'wb') as f:
            f.write(payload)
        m = hashlib.md5(payload).hexdigest()
        send_ack(fd)
        got[seq] = len(payload)
        results.append((seq, fn, len(payload), m))
        print('[RX]   [%3d/%d] seq=%-3d %4d B  md5=%s  -> %s'
              % (len(got), n_expect, seq, len(payload), m, os.path.basename(fn)))
        sys.stdout.flush()

    dt = time.time() - t_sess
    os.close(fd)

    missing = sorted(expected - set(got))
    print('=' * 68)
    print('[RX] 共收到 %d / %d 张，用时 %.1f s' % (len(got), len(expected), dt))
    print('[RX] 汇总（请发给 A 端核对）：')
    for seq, fn, ln, m in sorted(results):
        print('[RX]   rx%-4d %-14s %4d B  md5=%s' % (seq, os.path.basename(fn), ln, m))
    if missing:
        print('[RX] ⚠️ **缺第 %s 张** —— 让 A 端发 SESSION_RETRY 补发即可（不用整批重来）' % missing)
    print('[RX] RX_SESSION_DONE  got=%d/%d' % (len(got), len(expected)))

    if a.decode and results:
        print('[RX] 开始解码（一张约 57 s；N 大时建议只挑几张解）…')
        for seq, fn, ln, m in sorted(results):
            print('[RX]   --- 解码 %s ---' % os.path.basename(fn))
            rc = os.system('python3 /root/decode_board.py %s' % fn)
            print('[RX]     rc=%d' % rc)
            sys.stdout.flush()


if __name__ == '__main__':
    main()
