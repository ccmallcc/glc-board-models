#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A_send_session.py —— GLC 电台**会话模式**发送端 v2（2026-10-09）

解决什么问题
------------
B 端原来的 `radio_rx.py` 是"**收满一帧就 break**"，所以 A 每发一张，B 都要人工重启监听。
实测（7 张）：**总耗时 368 s，真正空口只占 4.8 s** —— 其余全在等人。
⇒ 只要 A 事先告诉 B「我要发 N 张」，B 一次开监听就能收完。

设计原则：**数据帧一个字节都不改**
--------------------------------
  · 数据帧：`AA 55 | seq | len(2B) | payload | sum`，seq 从 1 开始（与现在逐字节相同）
  · 控制帧只借用**保留值 SEQ = 0x00**（现有实现里 seq 不会出现 0）
  · ⇒ B 端**不改也能跑**（只是每张仍要人工重启）

v2 相比 v1 补了什么（针对"N 可能到 63"）
--------------------------------------
  ① **BEGIN 的长度段变成可选**（`--no-lens`）：不列长度时 BEGIN 只有 4 B，
     A 就可以"**发了 BEGIN 就开始边编码边发**"，不必等 N 张全部编码完。
  ② **补发机制**（控制帧 `0x13 SESSION_RETRY`）：大 N 时个别帧失败很正常，
     现在只补那几张，**不用整批重来**。
  ③ **进度显示**：`已发 k/N · 已确认 j/N`（A 端自己数，不需要改协议）
  ④ **连续失败中止**：连续 K 帧无应答就发 `SESSION_ABORT`，别傻等 40 次重试

用法（板子上）
--------------
    python3 /root/glc/A_send_session.py <glc1> <glc2> ... <glcN>

    # 不列长度（允许边编码边发，但 B 就不做长度校验）
    python3 /root/glc/A_send_session.py --no-lens *.glc

    # 每张最多重试 8 次；连续 5 张失败就整批中止；失败的最多补发 2 轮
    python3 /root/glc/A_send_session.py --attempts 8 --max-consec-fail 5 --retry-rounds 2 *.glc
"""
import argparse
import hashlib
import os
import struct
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

WANT_AT = (('AT+FREQ?', '470.110'), ('AT+SYMBOL?', '19.2'), ('AT+UART?', '115200'))


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


def drain(fd, secs, stop_on=None, idle=0.06, min_wait=0.06):
    u"""读串口，**最多** secs 秒；早读完就早返回。

    ★ 2026-10-23 改（原来是"无脑读满 secs"）：
      原实现 `while now - t0 < secs:` 不管电台多快应答都要等满整个超时，
      于是 8.2 s 的 AT 自检里 **8.1 s 是白等**（实测拆解：2.0 清缓冲 + 1.5 的 +++
      + 3×1.0 的三条查询 + 1.2 的 AT+EXIT + 0.5 收尾）。

      新规则（三条同时成立才返回，任一触发即走）：
        ① 响应里出现 stop_on 里的任一标记（例如 'OK'）⇒ 立刻返回
        ② 读过数据、且之后 idle 秒没有新数据（认为对方说完了）
        ③ 已经读满 min_wait（避免极端情况下一条都还没回来就走）
      但**永远不超过 secs** —— 原来的超时上限原封不动保留，所以最坏情况等于旧行为。

    min_wait / idle 是保守参数：电台刚上电时可能回得慢，留这 60~150 ms 兜底。
    """
    t0 = time.time()
    out = b''
    last = t0
    while True:
        now = time.time()
        if now - t0 >= secs:
            break
        try:
            c = os.read(fd, 512)
        except (BlockingIOError, OSError):
            c = b''
        if c:
            out += c
            last = time.time()
            if stop_on:
                for tok in stop_on:
                    if tok.encode() in out.upper():
                        return out
        else:
            now = time.time()
            if (now - t0) >= min_wait and (now - last) >= idle:
                break
        time.sleep(0.02)
    return out


def at(fd, cmd, wait=1.0, stop_on=('OK',), min_wait=0.12, idle=0.10):
    os.write(fd, (cmd + '\r\n').encode())
    return drain(fd, wait, stop_on=stop_on, min_wait=min_wait, idle=idle)


def at_retry(fd, cmd, want=None, tries=3, wait=1.0):
    got = ''
    for _ in range(tries):
        r = at(fd, cmd, wait).decode('utf-8', 'replace').strip()
        if r and (want is None or want in r):
            return r
        if len(r) > len(got):
            got = r
    return got


# ----------------------------------------------------------------- 组帧
def build_frame(seq, payload):
    """统一信封：AA 55 | seq | len(2B BE) | payload | sum(payload)&0xFF"""
    return (MAGIC + bytes([seq & 0xFF]) + len(payload).to_bytes(2, 'big')
            + payload + bytes([sum(payload) & 0xFF]))


def build_begin(n, mode, rate, lens=None, orig=None):
    """SESSION_BEGIN 的 PAYLOAD：CMD | N | MODE | RATE | [LEN_0..LEN_{N-1}] | [ORIG_W|ORIG_H|ORIG_BYTES]

    lens=None ⇒ 不列长度（PAYLOAD 只有 4 B）
    orig=(w, h, bytes) ⇒ 末尾再追加 8 字节（2+2+4，大端）：
        原图宽、原图高、原图文件字节数。

    ★ 2026-10-23 新增 ORIG（用户要求"发送的内容里体现 GLC 的优势"）：
      容器头里**没有分辨率/原始大小**，B 端只能看到"收到 xx 字节"，
      没法自己算出压缩比。带上 ORIG 之后 B 就能显示
        「原图 512×512 / 80.0 KB → GLC 1,084 B（75.6 : 1）」
      语义约定：**ORIG 只在"一次会话对应一张图"时有意义**
        · 小图 N=1  → 就是这张图的宽高与字节数
        · 大图 N=4  → 是那张 512 原图的宽高与字节数（不是分块的）
        · 小图 N>1  → 多张不同的图，**不带 ORIG**（带了会误导）
      长度判断（B 端按这个解析，向后兼容）：
        base   = 4
        lens   = 2*N（仅当 len(payload) >= 4 + 2*N 且 N>0）
        orig   = 8  （仅当 len(payload) >= 4 + 2*N + 8）
    """
    p = bytes([CMD_BEGIN, n & 0xFF, mode & 0xFF, rate & 0xFF])
    if lens:
        for L in lens:
            p += struct.pack('>H', L & 0xFFFF)
    if orig:
        ow, oh, ob = orig
        p += struct.pack('>HHI', ow & 0xFFFF, oh & 0xFFFF, ob & 0xFFFFFFFF)
    return build_frame(0, p)


def build_end(sent, ok):
    return build_frame(0, bytes([CMD_END, sent & 0xFF, ok & 0xFF]))


def build_abort(reason):
    return build_frame(0, bytes([CMD_ABORT, reason & 0xFF]))


def build_retry(seqs):
    """0x13 SESSION_RETRY: CMD | K | seq_1..seq_K"""
    p = bytes([CMD_RETRY, len(seqs) & 0xFF]) + bytes([s & 0xFF for s in seqs])
    return build_frame(0, p)


def wait_reply(fd, wait):
    """等一个 ACK/NAK；返回 (结果字符串|None, 耗时)"""
    t0 = time.time()
    buf = b''
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
            if st == ACK:
                return 'OK', time.time() - t0
            if st == NAK:
                return 'NAK', time.time() - t0
            return 'OTHER(0x%02x)' % st, time.time() - t0
        time.sleep(0.02)
    return None, time.time() - t0


def send_control(fd, frame, what, wait, gap, attempts, tag=''):
    """发一个控制帧并等确认（会重试）。返回 True/False"""
    for k in range(1, attempts + 1):
        os.write(fd, frame)
        res, dt = wait_reply(fd, wait)
        if res == 'OK':
            print('[SS]   ✅ %s 已确认（第 %d 次，%.2f s）%s' % (what, k, dt, tag))
            sys.stdout.flush()
            return True
        print('[SS]   %s 第 %d/%d 次：%s（%.2f s）—— %g s 后重试'
              % (what, k, attempts, res or '无应答', dt, gap))
        sys.stdout.flush()
        time.sleep(gap)
    return False


# ----------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('glcs', nargs='*')
    ap.add_argument('--mode', type=int, default=0,
                    help='发送模式：0=小图（每帧一张 256×256）；1=大图（本次会话正好 4 帧，'
                         '顺序 TL,TR,BL,BR，B 端拼成 512×512）。其它值保留')
    ap.add_argument('--rate', type=int, default=0, help='射频速率档（保留，0=19.2kbps）')
    ap.add_argument('--orig', default=None, metavar='WxH:BYTES',
                    help='原图尺寸与字节数，例如 512x512:80002；会写进 SESSION_BEGIN 末尾 8 字节，'
                         '用于 B 端显示压缩比（容器头里没有分辨率，靠这个补上）')
    ap.add_argument('--no-lens', action='store_true',
                    help='BEGIN 里不列逐张长度（B 就不做长度校验；允许边编码边发）')
    ap.add_argument('--begin-wait', type=float, default=6.0)
    ap.add_argument('--begin-attempts', type=int, default=99)
    ap.add_argument('--wait', type=float, default=6.0, help='每张等 ACK 的秒数')
    ap.add_argument('--gap', type=float, default=4.0, help='失败后隔多久重试')
    ap.add_argument('--attempts', type=int, default=8, help='每张最多重试几次')
    ap.add_argument('--max-consec-fail', type=int, default=5,
                    help='连续这么多张失败就整批中止（0=不中止）')
    ap.add_argument('--retry-rounds', type=int, default=2, help='失败者的补发轮数')
    ap.add_argument('--at-only', action='store_true',
                    help='只做清缓冲+AT自检+进透传就退出（用于与编码并行）')
    ap.add_argument('--at-done', action='store_true',
                    help='跳过 AT 自检（已经用 --at-only 做过了）')
    a = ap.parse_args()

    if not os.path.exists(DEV):
        print('[SS] 找不到 %s' % DEV)
        sys.exit(2)

    blobs = []
    for g in a.glcs:
        if not os.path.exists(g):
            print('[SS] 找不到容器 %s' % g)
            sys.exit(4)
        d = open(g, 'rb').read()
        blobs.append((os.path.basename(g), d, hashlib.md5(d).hexdigest()))
    N = len(blobs)
    if N > 254:
        print('[SS] 张数 %d 超过协议上限 254' % N)
        sys.exit(5)

    print('=' * 72)
    print('[SS] 会话模式发送：%d 张' % N)
    for i, (nm, d, m) in enumerate(blobs, 1):
        print('[SS]   %3d  %-16s %4d B  %s' % (i, nm, len(d), m))
    print('[SS]   BEGIN 里%s列长度 ｜ 每张最多试 %d 次 ｜ 连续失败 %d 张即中止 ｜ 补发 %d 轮'
          % ('' if a.no_lens else '会', a.attempts, a.max_consec_fail, a.retry_rounds))
    print('=' * 72)

    if a.at_done:
        print('[SS] 跳过 AT 自检（--at-done；已由 --at-only 做过）')
        fd = open_dev(115200)
    else:
        fd = open_dev(115200)
        t_setup = time.time()
        print('[SS] 清缓冲 2.0 s …')
        drain(fd, 2.0)
        at(fd, '+++', 1.5)
        ok = True
        for cmd, want in WANT_AT:
            resp = at_retry(fd, cmd, want, tries=3)
            hit = want in resp
            ok = ok and hit
            print('[SS]   %-11s -> %-46s [%s]' % (cmd, resp.replace('\n', ' ')[:46], 'OK' if hit else '不符'))
        if not ok:
            print('[SS] 参数不符，不发')
            os.close(fd)
            sys.exit(3)
        r = at(fd, 'AT+EXIT=1', 1.2).decode('utf-8', 'replace').strip()
        print('[SS] AT+EXIT=1 -> %r' % r)
        if 'OK' not in r:
            print('[SS] 没进透传模式')
            os.close(fd)
            sys.exit(6)
        time.sleep(0.5)
        print('[SS] AT 自检一次性耗时 %.2f s' % (time.time() - t_setup))
    if a.at_only:
        print('[SS] --at-only 完成，退出（电台已进透传）')
        os.close(fd)
        sys.exit(0)

    # ================= ① SESSION_BEGIN =================
    lens = None if a.no_lens else [len(d) for _, d, _ in blobs]
    # ★ MODE=1（大图）的契约：一次会话**正好 4 帧**。这样 B 端的判据最简单，
    #   不用从 N 里推"每几张拼一张"。多张大图 = 多个 N=4 会话。
    if a.mode == 1 and N != 4:
        print('[SS] !! MODE=1（大图）要求正好 4 个容器，收到 %d 个' % N)
        return 2
    # ORIG：只在"一次会话对应一张图"时携带（小图 N=1 / 大图 N=4）；多张不同图不带
    orig = None
    if a.orig:
        try:
            wh, ob = a.orig.split(':')
            ow, oh = wh.lower().split('x')
            orig = (int(ow), int(oh), int(ob))
        except Exception:
            print('[SS] !! --orig 格式应为 WxH:BYTES（例如 512x512:80002），收到 %r' % a.orig)
            os.close(fd)
            sys.exit(2)
        if N != 1 and a.mode != 1:
            print('[SS] !! 多张不同图（N=%d）不携带 ORIG，已忽略 --orig' % N)
            orig = None
    begin = build_begin(N, a.mode, a.rate, lens, orig)
    print('[SS] ① SESSION_BEGIN  N=%d  %s  （%d B 帧）'
          % (N, '不列长度' if a.no_lens else '逐张长度=%s' % lens, len(begin)))
    if orig:
        print('[SS]    原图 %dx%d  %d B ⇒ 载荷 %d B，压缩比 %.1f : 1'
              % (orig[0], orig[1], orig[2], sum(len(d) for _, d, _ in blobs),
                 orig[2] / max(1.0, sum(len(d) for _, d, _ in blobs))))
    if not send_control(fd, begin, 'SESSION_BEGIN', a.begin_wait, a.gap, a.begin_attempts,
                        tag='—— 对方现在应该开始连收 %d 帧' % N):
        print('[SS] ❌ 对方始终没确认 BEGIN，放弃（容器没发出去）')
        os.close(fd)
        sys.exit(7)

    # ================= ② 逐张发 =================
    acked = set()
    consecutive_fail = 0
    aborted = False
    t_data = time.time()

    def send_one(idx):
        """发第 idx 张（1 基），成功返回 True"""
        nm, d, m = blobs[idx - 1]
        fr = build_frame(idx, d)
        for k in range(1, a.attempts + 1):
            os.write(fd, fr)
            res, dt = wait_reply(fd, a.wait)
            if res == 'OK':
                print('[SS]     [%3d/%d] %-16s %4d B  OK  %.2f s（第 %d 次）'
                      % (idx, N, nm, len(d), dt, k))
                sys.stdout.flush()
                return True
            print('[SS]     [%3d/%d] %-16s 第 %d/%d 次：%s（%.2f s）'
                  % (idx, N, nm, k, a.attempts, res or '等 ACK 超时', dt))
            sys.stdout.flush()
            time.sleep(a.gap)
        print('[SS]     [%3d/%d] %-16s ❌ %d 次都没成功' % (idx, N, nm, a.attempts))
        sys.stdout.flush()
        return False

    print('[SS] ② 逐张发送（seq=1..%d）' % N)
    for i in range(1, N + 1):
        if send_one(i):
            acked.add(i)
            consecutive_fail = 0
        else:
            consecutive_fail += 1
            if a.max_consec_fail and consecutive_fail >= a.max_consec_fail:
                print('[SS] ⛔ 连续 %d 张失败 —— 整批中止' % consecutive_fail)
                send_control(fd, build_abort(1), 'SESSION_ABORT', 5.0, a.gap, 3,
                             tag='(reason=1 连续失败)')
                aborted = True
                break
        if i % 5 == 0 or i == N:
            print('[SS]     —— 进度：已发 %d/%d ｜ 已确认 %d/%d ——' % (i, N, len(acked), N))
            sys.stdout.flush()
    t_pass1 = time.time() - t_data

    # ================= ③ 补发失败者 =================
    rnd = 0
    while not aborted and a.retry_rounds > 0 and rnd < a.retry_rounds:
        missing = sorted(set(range(1, N + 1)) - acked)
        if not missing:
            break
        rnd += 1
        print('[SS] ③ 第 %d 轮补发：缺 %d 张 -> %s' % (rnd, len(missing), missing))
        rf = build_retry(missing)
        if not send_control(fd, rf, 'SESSION_RETRY(K=%d)' % len(missing), 6.0, a.gap, 10):
            print('[SS]   ⚠️ 补发请求没被确认，放弃补发')
            break
        for i in missing:
            if send_one(i):
                acked.add(i)
        print('[SS]   补发后：已确认 %d/%d' % (len(acked), N))

    # ================= ④ SESSION_END =================
    print('[SS] ④ SESSION_END  sent=%d ok=%d' % (N, len(acked)))
    if not aborted:
        send_control(fd, build_end(N, len(acked)), 'SESSION_END', 5.0, a.gap, 4)
    os.close(fd)

    missing = sorted(set(range(1, N + 1)) - acked)
    print('=' * 72)
    print('[SS] 数据段耗时 %.2f s   共 %d 张   成功 %d   缺 %d %s'
          % (t_pass1, N, len(acked), len(missing), missing if missing else ''))
    print('[SS] 请把下面几行发给对方核对：')
    for i, (nm, d, m) in enumerate(blobs, 1):
        print('[SS]   rx%-4d %-16s %4d B  md5=%s  %s'
              % (i, nm, len(d), m, 'OK' if i in acked else '** 缺 **'))
    print('[SS] SESSION_DONE  ok=%d/%d' % (len(acked), N))
    sys.exit(0 if not missing else 1)


if __name__ == '__main__':
    main()
