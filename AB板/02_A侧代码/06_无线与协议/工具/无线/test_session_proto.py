#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_session_proto.py —— 会话协议自测 v2（**不需要电台**）

两层测试：
  A. **单元层**：用管道把 A 端构造的字节流喂给 B 端的 `Reader`，验证组帧/切帧/校验
  B. **集成层**：用 **PTY 假装串口**，把 `radio_rx_session.py` **当子进程真跑起来**，
     从"串口"另一头灌数据流，检查它是否把 N 张都存对、ACK 是否发对、RETRY 是否生效

集成层是这轮重点：验证的是**B 端脚本的真实行为**，而不是我重写一遍逻辑。

跑法（PC 或板子上都行）：
    python3 test_session_proto.py
"""
import os
import pty
import random
import select
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
for d in (HERE, "/root/glc", "/root"):
    if d not in sys.path:
        sys.path.insert(0, d)

import A_send_session as A          # noqa: E402
import radio_rx_session as B        # noqa: E402


# ======================================================================
# A. 单元层：管道喂给 Reader
# ======================================================================
def feed(blob, chunk=0):
    r, w = os.pipe()
    if chunk <= 0:
        os.write(w, blob)
    else:
        for i in range(0, len(blob), chunk):
            os.write(w, blob[i:i + chunk])
    os.close(w)
    os.set_blocking(r, False)
    return r


def t_unit_normal():
    print('=== A1 单元：正常会话（BEGIN + 7 帧 + END）===')
    ps = [bytes(random.getrandbits(8) for _ in range(random.randint(300, 350))) for _ in range(7)]
    blob = A.build_begin(7, 0, 0, [len(p) for p in ps])
    for i, p in enumerate(ps, 1):
        blob += A.build_frame(i, p)
    blob += A.build_end(7, 7)
    rd = B.Reader(feed(blob))
    seq, pl, why = rd.next_frame(2.0)
    assert seq == 0 and pl[0] == A.CMD_BEGIN, (seq, why)
    n, mode, rate, lens = B.parse_begin(pl)
    assert n == 7 and lens == [len(p) for p in ps], (n, lens)
    for i in range(1, 8):
        seq, p, why = rd.next_frame(2.0)
        assert seq == i and p == ps[i - 1], (i, seq, why)
    seq, p, why = rd.next_frame(2.0)
    assert seq == 0 and p[0] == A.CMD_END and p[1] == 7 and p[2] == 7
    print('   ✅ 7 帧 + END 全部正确')
    return True


def t_unit_n63():
    print('=== A2 单元：N=63（长度段 4+126=130 B）===')
    ps = [bytes([i & 0xFF]) * (300 + i) for i in range(1, 64)]
    blob = A.build_begin(63, 0, 0, [len(p) for p in ps])
    print('   BEGIN 帧 %d B（PAYLOAD %d B）' % (len(blob), len(blob) - 6))
    for i, p in enumerate(ps, 1):
        blob += A.build_frame(i, p)
    rd = B.Reader(feed(blob))
    seq, pl, why = rd.next_frame(3.0)
    n, mode, rate, lens = B.parse_begin(pl)
    assert n == 63 and lens == [len(p) for p in ps], (n, len(lens or []))
    print('   ✅ BEGIN 正确解析：N=%d，长度段 %d 项' % (n, len(lens)))
    for i in range(1, 64):
        seq, p, why = rd.next_frame(3.0)
        assert seq == i and p == ps[i - 1], (i, seq, why)
    print('   ✅ 63 帧全部正确解析')
    return True


def t_unit_nolens():
    print('=== A3 单元：BEGIN 不带长度段（--no-lens）===')
    blob = A.build_begin(5, 0, 0, None)
    assert len(blob) == 6 + 4, len(blob)
    rd = B.Reader(feed(blob))
    seq, pl, why = rd.next_frame(2.0)
    n, mode, rate, lens = B.parse_begin(pl)
    assert n == 5 and lens is None, (n, lens)
    print('   ✅ BEGIN 只有 4 B PAYLOAD；parse_begin 返回 lens=None（跳过长度校验）')
    return True


def t_unit_frag():
    print('=== A4 单元：串口碎片（每 3 字节写一次）===')
    ps = [bytes([i] * 40) for i in range(1, 4)]
    blob = A.build_begin(3, 0, 0, [len(p) for p in ps])
    for i, p in enumerate(ps, 1):
        blob += A.build_frame(i, p)
    rd = B.Reader(feed(blob, chunk=3))
    seq, pl, why = rd.next_frame(3.0)
    assert seq == 0 and B.parse_begin(pl)[0] == 3, (seq, why)
    for i in range(1, 4):
        seq, p, why = rd.next_frame(3.0)
        assert seq == i and p == ps[i - 1], (i, seq, why)
    print('   ✅ 分片到达也能正确切帧')
    return True


def t_unit_noise():
    print('=== A5 单元：帧前有噪声 ===')
    p = b'hello-glc-container' * 15
    blob = b'\x00\x01\x02rubbish\xaa' + A.build_begin(1, 0, 0, [len(p)]) + A.build_frame(1, p)
    rd = B.Reader(feed(blob))
    seq, pl, why = rd.next_frame(3.0)
    assert seq == 0, (seq, pl, why)
    seq, pp, why = rd.next_frame(3.0)
    assert seq == 1 and pp == p, (seq, pp, why)
    print('   ✅ 噪声前缀被跳过')
    return True


def t_unit_badsum():
    print('=== A6 单元：校验和被改坏 ===')
    fr = bytearray(A.build_frame(1, b'ABCDEFGH' * 10))
    fr[-1] = (fr[-1] + 1) & 0xFF
    rd = B.Reader(feed(bytes(fr)))
    seq, p, why = rd.next_frame(2.0)
    assert seq is None and why and '校验和' in why, (seq, p, why)
    print('   ✅ 检测到：%s' % why)
    return True


# ======================================================================
# B. 集成层：PTY 假装串口，把 B 端脚本当子进程真跑
# ======================================================================
class FakeRadio(object):
    """PTY 主端：对 B 脚本来说它就是 /dev/ttyUSB0。"""

    def __init__(self):
        self.master, self.slave = pty.openpty()
        self.slave_name = os.ttyname(self.slave)
        self.saw_at = False

    def close(self):
        for f in (self.master, self.slave):
            try:
                os.close(f)
            except OSError:
                pass

    def pump_at(self, seconds=10.0):
        """模拟电台的 AT 握手：看到 AT+EXIT=1 就回 OK。

        ⚠️ 窗口必须够长：B 脚本的时序是
             drain 1.5s -> 写 '+++' -> drain 1.5s -> 写 'AT+EXIT=1' -> drain 1.5s
           也就是 **t≈3.0 s 才会发 AT+EXIT=1**。
           第一次只轮询 3.0 s，正好错过，导致后续把数据帧当成 AT 应答读走了。
        返回 True 表示握手确实完成了。
        """
        t0 = time.time()
        buf = bytearray()
        while time.time() - t0 < seconds:
            r, _, _ = select.select([self.master], [], [], 0.1)
            if not r:
                continue
            try:
                d = os.read(self.master, 4096)
            except OSError:
                break
            if not d:
                break
            buf += d
            if not self.saw_at and b'AT+EXIT=1' in bytes(buf):
                os.write(self.master, b'\r\nOK\r\n')
                self.saw_at = True
                # ★★ 关键：必须等脚本把**它自己的最后一次 drain(1.5s) 跑完**再发数据。
                #   脚本时序：drain1.5 -> 写'+++' -> drain1.5 -> 写'AT+EXIT=1' -> drain1.5
                #   t≈3.0 才写 AT+EXIT=1，t≈4.5 才 drain 完。
                #   早发的话，数据会被那次 drain 当成 AT 应答吃掉（这个坑踩过一次）。
                time.sleep(2.5)
                return True
        return self.saw_at

    def send(self, blob, pace=0):
        if pace <= 0:
            os.write(self.master, blob)
        else:
            for i in range(0, len(blob), pace):
                os.write(self.master, blob[i:i + pace])
                time.sleep(0.008)

    def collect(self, seconds):
        out = bytearray()
        t0 = time.time()
        while time.time() - t0 < seconds:
            r, _, _ = select.select([self.master], [], [], 0.1)
            if r:
                try:
                    d = os.read(self.master, 4096)
                except OSError:
                    break
                out += d
        return bytes(out)


def run_rx_script(radio, outdir, timeout=180.0):
    """把子进程输出**写到文件**而不是 PIPE：
    这样它卡住时我们也能随时读到输出（PIPE 要等进程退出才能读）。"""
    env = dict(os.environ)
    env['GLC_RADIO_DEV'] = radio.slave_name
    logf = open(os.path.join(outdir, '_rx.log'), 'w')
    cmd = [sys.executable, '-u', os.path.join(HERE, 'radio_rx_session.py'),
           '-d', outdir, '-t', str(timeout), '--idle-timeout', '3']
    return subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, env=env,
                            universal_newlines=True)


def read_log(outdir, tail=40000):
    try:
        with open(os.path.join(outdir, '_rx.log')) as f:
            return f.read()[-tail:]
    except Exception as e:
        return '<读不到日志: %s>' % e


def finish(proc, outdir, timeout):
    """等进程结束；超时就杀掉，并把已有的日志返回（便于诊断）。"""
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
        return read_log(outdir) + '\n<<< 超时未退出，已杀掉 >>>'
    return read_log(outdir)


def t_int_normal():
    print('=== B1 集成：PTY 假装串口，B 脚本真跑，收 7 张 ===')
    outdir = tempfile.mkdtemp(prefix='glcrx_')
    radio = FakeRadio()
    proc = run_rx_script(radio, outdir)
    try:
        assert radio.pump_at(10.0), 'AT 握手没完成（模拟电台没回 OK）'
        time.sleep(0.5)
        ps = [bytes(random.getrandbits(8) for _ in range(300 + i * 3)) for i in range(7)]
        blob = A.build_begin(7, 0, 0, [len(p) for p in ps])
        for i, p in enumerate(ps, 1):
            blob += A.build_frame(i, p)
        blob += A.build_end(7, 7)
        radio.send(blob, pace=97)
        ack = radio.collect(4.0)
        outs = finish(proc, outdir, 20)
        if 'RX_SESSION_DONE' not in outs:
            print('   ---- 子进程输出 ----'); print(outs); print('   --------------------')
        files = sorted(f for f in os.listdir(outdir) if f.endswith('.glc'))
        assert len(files) == 7, '只存了 %d 个文件: %s' % (len(files), files)
        for i, p in enumerate(ps, 1):
            d = open(os.path.join(outdir, 'rx%d.glc' % i), 'rb').read()
            assert d == p, 'rx%d.glc 内容不符' % i
        n_ack = ack.count(b'\xaa\x55\x06')
        assert n_ack >= 9, 'ACK 只有 %d 个（期望 >=9：BEGIN+7帧+END）' % n_ack
        assert 'SESSION_BEGIN' in outs and 'RX_SESSION_DONE  got=7/7' in outs, outs[-400:]
        print('   ✅ 7 个文件内容全对；ACK %d 个（>=9）；脚本自报 got=7/7' % n_ack)
        return True
    finally:
        try:
            proc.kill()
        except Exception:
            pass
        radio.close()
        shutil.rmtree(outdir, ignore_errors=True)


def t_int_n63_retry():
    print('=== B2 集成：N=63 + 第一轮丢 3 帧 + SESSION_RETRY 补发 ===')
    outdir = tempfile.mkdtemp(prefix='glcrx_')
    radio = FakeRadio()
    proc = run_rx_script(radio, outdir, timeout=60.0)
    try:
        assert radio.pump_at(10.0), 'AT 握手没完成（模拟电台没回 OK）'
        time.sleep(0.5)
        N = 63
        ps = [bytes([(i * 7) & 0xFF]) * (300 + (i % 40)) for i in range(1, N + 1)]
        blob = A.build_begin(N, 0, 0, [len(p) for p in ps])
        drop = [17, 42, 60]
        for i, p in enumerate(ps, 1):
            if i in drop:
                continue
            blob += A.build_frame(i, p)
        blob += A.build_retry(drop)
        for i in drop:
            blob += A.build_frame(i, ps[i - 1])
        blob += A.build_end(N, N)
        radio.send(blob, pace=131)
        radio.collect(4.0)
        outs = finish(proc, outdir, 25)
        if 'RX_SESSION_DONE' not in outs:
            print('   ---- 子进程输出 ----'); print(outs[-2500:]); print('   --------------------')
        files = sorted(f for f in os.listdir(outdir) if f.endswith('.glc'))
        assert len(files) == N, '只存了 %d 个文件（期望 %d）' % (len(files), N)
        for i, p in enumerate(ps, 1):
            d = open(os.path.join(outdir, 'rx%d.glc' % i), 'rb').read()
            assert d == p, 'rx%d.glc 内容不符' % i
        assert 'SESSION_RETRY' in outs, '没看到 RETRY 处理日志'
        assert 'RX_SESSION_DONE  got=63/63' in outs, outs[-500:]
        print('   ✅ 63 个文件内容全对（含补发的 3 张）；RETRY 被正确处理；自报 got=63/63')
        return True
    finally:
        try:
            proc.kill()
        except Exception:
            pass
        radio.close()
        shutil.rmtree(outdir, ignore_errors=True)


def t_int_nolens():
    print('=== B3 集成：BEGIN 不带长度段 + N=10 ===')
    outdir = tempfile.mkdtemp(prefix='glcrx_')
    radio = FakeRadio()
    proc = run_rx_script(radio, outdir, timeout=30.0)
    try:
        assert radio.pump_at(10.0), 'AT 握手没完成（模拟电台没回 OK）'
        time.sleep(0.5)
        ps = [bytes([i]) * (280 + i) for i in range(1, 11)]
        blob = A.build_begin(10, 0, 0, None)
        for i, p in enumerate(ps, 1):
            blob += A.build_frame(i, p)
        blob += A.build_end(10, 10)
        radio.send(blob, pace=53)
        radio.collect(4.0)
        outs = finish(proc, outdir, 20)
        if 'RX_SESSION_DONE' not in outs:
            print('   ---- 子进程输出 ----'); print(outs); print('   --------------------')
        files = sorted(f for f in os.listdir(outdir) if f.endswith('.glc'))
        assert len(files) == 10, files
        for i, p in enumerate(ps, 1):
            assert open(os.path.join(outdir, 'rx%d.glc' % i), 'rb').read() == p
        assert '没列长度' in outs, outs[-400:]
        assert 'RX_SESSION_DONE  got=10/10' in outs
        print('   ✅ 10 张全对；脚本正确识别"没列长度、跳过校验"')
        return True
    finally:
        try:
            proc.kill()
        except Exception:
            pass
        radio.close()
        shutil.rmtree(outdir, ignore_errors=True)


def t_int_abort():
    print('=== B4 集成：SESSION_ABORT 应立即收摊 ===')
    outdir = tempfile.mkdtemp(prefix='glcrx_')
    radio = FakeRadio()
    proc = run_rx_script(radio, outdir, timeout=30.0)
    try:
        assert radio.pump_at(10.0), 'AT 握手没完成（模拟电台没回 OK）'
        time.sleep(0.5)
        blob = A.build_begin(5, 0, 0, None)
        blob += A.build_frame(1, b'X' * 300)
        blob += A.build_abort(1)
        radio.send(blob, pace=61)
        radio.collect(2.0)
        outs = finish(proc, outdir, 12)
        assert '中止' in outs, outs[-400:]
        print('   ✅ 收到 ABORT 后正常收摊')
        return True
    finally:
        try:
            proc.kill()
        except Exception:
            pass
        radio.close()
        shutil.rmtree(outdir, ignore_errors=True)


def main():
    random.seed(20261009)
    tests = [t_unit_normal, t_unit_n63, t_unit_nolens, t_unit_frag, t_unit_noise,
             t_unit_badsum, t_int_normal, t_int_n63_retry, t_int_nolens, t_int_abort]
    passed = 0
    for t in tests:
        try:
            if t():
                passed += 1
        except AssertionError as e:
            print('   ❌ 失败: %s' % (e,))
        except Exception as e:
            import traceback
            traceback.print_exc()
            print('   ❌ 异常: %s' % e)
        print()
    print('=' * 62)
    print('自测结果：%d / %d 通过' % (passed, len(tests)))
    print('PROTO_TEST_DONE')
    return 0 if passed == len(tests) else 1


if __name__ == '__main__':
    sys.exit(main())
