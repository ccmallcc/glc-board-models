#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""radio_rx_serve.py —— GLC 电台接收端【选项 C：常驻监听】参考实现
（A 端编写，2026-10-15；配套 `80_给B_多图接收对接说明_20261015.md` §三 选项 C）

它解决什么问题
--------------
A 端触摸屏的「多选 + 发送队列」发 N 张时，**是 N 个独立的 N=1 会话**，不是一个 N 张的会话。
所以 `radio_rx_session.py`（收完一个会话就退出）**只会收到第一张**，第二张起无人应答 ——
A 端会在第 2 张报 `rc=7`（BEGIN 没人确认）。这条 2026-10-15 已经**真发实测到了**（见 `80` 号文文首）。

**本脚本一个进程常驻，把每一个到来的会话都收掉**，直到 `--max-sessions` 收满、或收到信号。

与 `radio_rx_session.py` 的关系（重要）
--------------------------------------
  · 帧格式 / 切帧 / ACK / BEGIN 解析**全部复用** `radio_rx_session.py` —— 协议一个字节没改。
  · **`radio_rx_session.py` 保持原样不动**（B 板现在跑的就是它，不要为了本脚本去改它）。
  · 本文件只是它的"**常驻外壳**"，区别只有三点：
      ① `fd` 只开一次、AT 握手只做一次  ← **这就是 4.5 s 盲窗消失的原因**
      ② 每个会话收完**不关 fd、不退出**，接着等下一个 `SESSION_BEGIN`
      ③ **每个会话写自己的子目录** —— 否则 N 个会话都写 `rx1.glc`，**互相覆盖、而且日志全绿**
         （这是最容易白干一场的坑，见 `80` 号文 §三「第 0 条」）

用法
----
    # 常驻（推荐，演示就挂这个；Ctrl-C 或 kill 退出）
    python3 /root/radio_rx_serve.py

    # 收满 3 个会话就退出（联调/自测用）
    python3 /root/radio_rx_serve.py --max-sessions 3

    # 换保存目录（默认 /root/glc/pack/rxs）
    python3 /root/radio_rx_serve.py -d /root/glc/pack/rxs

退出码
------
    0  正常退出（收满 --max-sessions，或收到 SIGINT/SIGTERM）
    2  找不到电台设备
    6  没能让电台进入透传模式

★ 两个必须知道的注意点
---------------------
1. **会话之间不要做耗时长的事**（例如 `--decode` 一张约 57 s）。
   A 端等 BEGIN 的窗口只有 **30 s**（`--begin-attempts 3`，每次"等 6 s + 隔 4 s"）。
   所以本脚本的 `--decode` **默认在整个常驻循环结束后才跑**，不会卡住下一个会话。
2. **不要用"睡一段时间不读"的写法**（`radio_rx_session.py:100` 的 `drain(fd, 1.5)` 那种）——
   那正是 4.5 s 盲窗的来源。会话之间本脚本**什么都不做**：
   `Reader.buf` 留着，迟到字节由 `next_frame()` 自己按 `AA 55` 重新同步（`:144-151`）。

自测（**不需要电台**，用 PTY 假电台）
------------------------------------
    python3 /root/test_rx_serve_pty.py          # 被测：本脚本；对照：radio_rx_session.py
"""
import argparse
import hashlib
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from radio_rx_session import (                                        # noqa: E402
    CMD_ABORT, CMD_BEGIN, CMD_END, CMD_RETRY, Reader, enter_transparent,
    open_dev, parse_begin, send_ack,
)

STOP = {'flag': False, 'sig': 0, 'why': ''}

HEARTBEAT = 60.0        # 等 BEGIN 期间每隔多久打一次"还在等"


def _on_signal(signum, frame):
    STOP['flag'] = True
    STOP['sig'] = signum
    print('\n[SV] 收到信号 %d —— 当前会话收完就退出' % signum)
    sys.stdout.flush()


def make_sdir(a, k):
    """每个会话一个子目录（`--flat` 时退回老行为，不推荐）。"""
    if a.flat:
        return a.dir
    d = os.path.join(a.dir, 's%04d_%s' % (k, time.strftime('%Y%m%d_%H%M%S')))
    os.makedirs(d, exist_ok=True)
    return d


def run_session(fd, rd, a, k):
    """跑一个完整会话：等 BEGIN → 收 N 帧 → 汇总。返回 dict。

    ★ 本函数**绝不关闭 fd**，也**绝不 sys.exit** —— 常驻模式下这两件事都得由 main() 决定，
      少改一处，下一个会话就收不到帧。

    返回：{n_expect, expected, got, results, dt, ended}
      ended ∈ 'end'(收到 SESSION_END) | 'abort' | 'idle'(会话内空闲超时) | 'stray' | 'sig'
    """
    sdir = make_sdir(a, k)
    n_expect = 0
    lens = None
    expected = set()
    got = {}
    results = []

    # ---------------------------------------------------------- 等 BEGIN
    print('=' * 68)
    print('[SV] ── 第 %d 个会话：等 SESSION_BEGIN ──' % k)
    if a.timeout > 0:
        print('[SV]    最多等 %.0f s（--timeout；0 = 一直等）' % a.timeout)
    else:
        print('[SV]    一直等（Ctrl-C 退出）；A 端等 BEGIN 的窗口只有 30 s，所以别在这里走神')
    print('[SV]    保存到 %s' % sdir)
    sys.stdout.flush()

    t0 = time.time()
    t_beat = t0
    while True:
        if STOP['flag']:
            return dict(n_expect=0, expected=set(), got={}, results=[],
                        dt=time.time() - t0, ended='sig')
        if a.timeout > 0 and time.time() - t0 > a.timeout:
            print('[SV] ❌ %.0f s 内没等到 BEGIN' % a.timeout)
            return dict(n_expect=0, expected=set(), got={}, results=[],
                        dt=time.time() - t0, ended='idle')
        seq, payload, why = rd.next_frame(5.0)
        if seq is None:
            if why and '校验和' in why:
                print('[SV] %s -> 回 NAK' % why)
                send_ack(fd, nak=True)
            elif time.time() - t_beat >= HEARTBEAT:
                t_beat = time.time()
                print('[SV]    …还在等 BEGIN（已等 %.0f s）' % (time.time() - t0))
                sys.stdout.flush()
            continue
        if seq != 0:
            # ★ 常驻模式：等 BEGIN 时收到数据帧 = 迟到/杂散，当噪声忽略。
            #   （老脚本这里是"旧式单帧"分支：存文件 + ACK + 结束会话 —— 常驻下等于一轮白跑）
            print('[SV]   （常驻）等 BEGIN 时收到数据帧 seq=%d（%d B）—— 当噪声忽略'
                  % (seq, len(payload)))
            sys.stdout.flush()
            continue
        cmd = payload[0] if payload else -1
        if cmd == CMD_BEGIN:
            n_expect, mode, rate, lens = parse_begin(payload)
            expected = set(range(1, n_expect + 1))
            send_ack(fd)
            print('[SV] ✅ 第 %d 个会话 SESSION_BEGIN：本次要收 **%d 张**  mode=%d rate=%d'
                  % (k, n_expect, mode, rate))
            if lens:
                print('[SV]    逐张长度 = %s' % lens)
            else:
                print('[SV]    （A 端没列长度，本次不做长度校验）')
            print('[SV]    已回 ACK —— 接下来连收，收到 SESSION_END / ABORT / 空闲超时为止')
            sys.stdout.flush()
            break
        if cmd == CMD_ABORT:
            send_ack(fd)
            print('[SV] 第 %d 个会话：A 端开单就中止（reason=%d）'
                  % (k, payload[1] if len(payload) > 1 else -1))
            return dict(n_expect=0, expected=set(), got={}, results=[],
                        dt=time.time() - t0, ended='abort')
        print('[SV] 收到未知控制帧 CMD=0x%02X，忽略' % cmd)

    # ---------------------------------------------------- 会话内：连收
    #   ★ 不靠"数够 N 帧"结束 —— 这样 A 端的补发(SESSION_RETRY)能自然插进来
    t_sess = time.time()
    ended = 'idle'
    while True:
        if STOP['flag']:
            ended = 'sig'
            break
        seq, payload, why = rd.next_frame(a.idle_timeout)
        if seq is None:
            if why and '校验和' in why:
                print('[SV]   %s -> 回 NAK' % why)
                send_ack(fd, nak=True)
                continue
            print('[SV] ⏰ 本会话空闲 %.0f s 没收到帧，收摊（进程不退，继续等下一个会话）'
                  % a.idle_timeout)
            ended = 'idle'
            break
        if seq == 0:
            cmd = payload[0] if payload else -1
            if cmd == CMD_END:
                send_ack(fd)
                print('[SV] SESSION_END：对方报告 sent=%d ok=%d'
                      % (payload[1] if len(payload) > 1 else -1,
                         payload[2] if len(payload) > 2 else -1))
                ended = 'end'
            elif cmd == CMD_ABORT:
                send_ack(fd)
                print('[SV] A 端中止会话（reason=%d）'
                      % (payload[1] if len(payload) > 1 else -1))
                ended = 'abort'
            elif cmd == CMD_RETRY:
                kk = payload[1] if len(payload) > 1 else 0
                seqs = list(payload[2:2 + kk])
                expected |= set(seqs)
                send_ack(fd)
                print('[SV] SESSION_RETRY：对方要补发 %d 张 -> %s（等着收）' % (kk, seqs))
            elif cmd == CMD_BEGIN:
                n2, _, _, lens2 = parse_begin(payload)
                send_ack(fd)
                print('[SV] 又收到 SESSION_BEGIN（N=%d）—— 按新会话继续收' % n2)
                n_expect, lens = n2, lens2
                expected |= set(range(1, n2 + 1))
            else:
                print('[SV] 会话中收到未知控制帧 0x%02X，忽略' % cmd)
            sys.stdout.flush()
            if ended != 'idle':
                break
            continue

        # ---- 数据帧：验长度（若有）→ 存盘 → ACK ----
        exp = lens[seq - 1] if (lens and 1 <= seq <= len(lens)) else None
        if exp is not None and exp != len(payload):
            print('[SV]   seq=%-3d ⚠️ 长度不符：收到 %d B，BEGIN 里说 %d B —— 仍然存下并 ACK'
                  % (seq, len(payload), exp))
        fn = os.path.join(sdir, 'rx%d.glc' % seq)
        with open(fn, 'wb') as f:
            f.write(payload)
        m = hashlib.md5(payload).hexdigest()
        send_ack(fd)
        got[seq] = len(payload)
        results.append((seq, fn, len(payload), m))
        print('[SV]   [%3d/%d] seq=%-3d %4d B  md5=%s  -> %s'
              % (len(got), n_expect, seq, len(payload), m, os.path.relpath(fn, a.dir)))
        sys.stdout.flush()

    dt = time.time() - t_sess

    # ---------------------------------------------------------- 汇总
    missing = sorted(expected - set(got))
    print('-' * 68)
    print('[SV] 第 %d 个会话：共收到 %d / %d 张，用时 %.1f s（结束原因 %s）'
          % (k, len(got), len(expected), dt, ended))
    for seq, fn, ln, m in sorted(results):
        print('[SV]   rx%-4d %-24s %4d B  md5=%s'
              % (seq, os.path.relpath(fn, a.dir), ln, m))
    if missing:
        print('[SV] ⚠️ **本会话缺第 %s 张** —— 让 A 端发 SESSION_RETRY 补发即可（不用整批重来）'
              % missing)
    print('[SV] RX_SERVE_SESSION_DONE k=%d got=%d/%d ended=%s'
          % (k, len(got), len(expected), ended))
    sys.stdout.flush()

    return dict(n_expect=n_expect, expected=expected, got=got, results=results,
                dt=dt, ended=ended)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-d', '--dir', default='/root/glc/pack/rxs', help='保存目录')
    ap.add_argument('-t', '--timeout', type=float, default=0.0,
                    help='等下一个 SESSION_BEGIN 的超时（秒）；**0 = 一直等**（常驻默认）')
    ap.add_argument('--idle-timeout', type=float, default=60.0,
                    help='会话内"多久没帧就收摊"（秒），默认 60。★ 只作用在会话内，不会让进程退出')
    ap.add_argument('--max-sessions', type=int, default=0,
                    help='收满这么多个会话就退出（0 = 永不退出），默认 0')
    ap.add_argument('--decode', action='store_true',
                    help='★ 整个常驻循环**结束后**再解码（不在会话之间做，否则会卡住下一个会话）')
    ap.add_argument('--flat', action='store_true',
                    help='⚠️ 不建每会话子目录（退回 rx1.glc 命名）—— **多个 N=1 会话会互相覆盖**，慎用')
    a = ap.parse_args()

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    from radio_rx_session import DEV
    if not os.path.exists(DEV):
        print('[SV] 找不到 %s（可用环境变量 GLC_RADIO_DEV 覆盖）' % DEV)
        sys.exit(2)
    if not os.path.isdir(a.dir):
        os.makedirs(a.dir)
    if a.flat:
        print('[SV] ⚠️ --flat：所有会话共用 %s/rxN.glc —— **N 个 N=1 会话会互相覆盖**' % a.dir)

    print('=' * 68)
    print('[SV] GLC 电台接收端 · **常驻模式**（选项 C）')
    print('[SV]   电台      %s' % DEV)
    print('[SV]   保存目录  %s%s' % (a.dir, '' if not a.flat else '（flat）'))
    print('[SV]   会话上限  %s' % ('永不退出' if a.max_sessions == 0 else a.max_sessions))
    print('[SV]   会话内空闲超时 %.0f s（不会让进程退出）' % a.idle_timeout)
    print('=' * 68)
    sys.stdout.flush()

    # ★★ 整个进程只做一次：开串口 + AT 握手 + 进透传
    fd = open_dev(115200)
    if not enter_transparent(fd):
        print('[SV] 没进透传模式，退出。请检查电台（重新上电 / AT+EXIT=1）')
        os.close(fd)
        sys.exit(6)

    rd = Reader(fd)
    print('[SV] ✅ 已进透传 —— **从现在起串口保持打开、AT 握手不再重做**')
    print('[SV]    串口一旦关了再开，就要重付 4.5 s 盲窗并可能丢帧；这就是要常驻的原因')
    sys.stdout.flush()

    all_results = []
    k = 0
    while not STOP['flag']:
        if a.max_sessions and k >= a.max_sessions:
            print('[SV] 收满 %d 个会话，退出' % a.max_sessions)
            break
        k += 1
        r = run_session(fd, rd, a, k)
        all_results.extend(r['results'])
        if r['ended'] == 'sig':
            break
        # ★ 会话之间**什么都不做**：不 drain、不 close、不 sleep 大段
        #   `Reader.buf` 留着；迟到字节由 next_frame() 自己按 AA 55 重同步
        #   （保留一个空转判断，方便 Ctrl-C 立刻生效）
        if STOP['flag']:
            break

    print('=' * 68)
    print('[SV] 常驻结束：共 %d 个会话、%d 个文件' % (k, len(all_results)))
    for seq, fn, ln, m in all_results:
        print('[SV]   %-30s %4d B  md5=%s' % (os.path.relpath(fn, a.dir), ln, m))

    if a.decode and all_results:
        print('[SV] 开始解码（一张约 57 s；N 大时建议只挑几张解）…')
        for seq, fn, ln, m in all_results:
            print('[SV]   --- 解码 %s ---' % os.path.basename(fn))
            rc = os.system('python3 /root/decode_board.py %s' % fn)
            print('[SV]     rc=%d' % rc)
            sys.stdout.flush()

    os.close(fd)
    print('[SV] RX_SERVE_DONE sessions=%d files=%d sig=%d'
          % (k, len(all_results), STOP['sig']))
    sys.exit(0)


if __name__ == '__main__':
    main()
