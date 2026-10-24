#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_rx_serve_pty.py —— 用 PTY「假电台」验证常驻接收（**完全不需要电台**）
（A 端编写，2026-10-15；配套 `radio_rx_serve.py` / `80` 号文 §三 选项 C）

为什么要有这个测试
------------------
「选项 C 常驻」最容易**白干一场**的坑是：
  **每个会话都写 `rx1.glc` ⇒ N 个会话互相覆盖 ⇒ 收完 10 张磁盘上只剩 1 张，而日志 10 行全绿。**
这个坑**看日志发现不了**，必须**真的去数文件、比 md5**。

场景按**真实用法**搭：**3 个会话、每个会话 1 张**（UI 队列发 3 张就是这个形状）。

本测试做两件事（**缺一不可**）：

  ① **被测**：`radio_rx_serve.py -d <tmp> --max-sessions 3`
     期望 → 3 个会话全部 ACK、**3 个独立子目录**、**3 个文件**、md5 与发出的 3 张**逐一对上**

  ② **对照（必须能失败）**：`radio_rx_session.py`（B 板现状：收完一批就退出）
     期望 → **第 1 个会话 OK，第 2、3 个会话收不到 ACK，磁盘上只有 1 个文件**
     ★ 只跑 ① 不跑 ② 的话，"通过"没有判别力 —— **一个永远 PASS 的判据等于没有判据**。

假电台怎么工作
--------------
  · 让被测进程连到 **PTY 从端**（`radio_rx_session.py:56` 本来就支持 `GLC_RADIO_DEV` 覆盖）。
  · 本测试开一个线程扮演「电台 + A 端」：
      - 看到 `AT+EXIT=1` ⇒ 回 `OK`（让 `enter_transparent()` 通过）
      - 之后按会话发：`SESSION_BEGIN` → 数据帧 → `SESSION_END`，**逐条等 ACK**
  · 帧**用 `A_send_session.py` 自己的构造函数**造（`build_begin/build_frame/build_end`）——
    保证测的是**真协议**，不是我另写一套；将来协议变了这个测试会跟着变。

跑法（板子上，或任何有 `pty` 的 Linux）：
    python3 /root/test_rx_serve_pty.py

退出码：0 = 两项都符合预期；1 = 有不符合的项。
"""
import hashlib
import os
import pty
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from A_send_session import build_begin, build_end, build_frame      # noqa: E402

ACK = b'\xAA\x55\x06'
NAK = b'\xAA\x55\x15'
PY = sys.executable or 'python3'

# 3 个会话各 1 张，**三张内容不同**（这样"互相覆盖"才会在 md5 上暴露出来）
IMAGES = [bytes([0x40 + i]) * (300 + 8 * i) for i in range(3)]


class FakeRadio(object):
    """扮演「电台」（答 AT）和「A 端」（发会话）。只数 ACK，不解析别的。"""

    def __init__(self, master):
        self.m = master
        self.buf = b''
        self.acks = 0
        self.at_replied = False
        self.alive = True
        self.lock = threading.Lock()
        self.th = threading.Thread(target=self._loop)
        self.th.daemon = True
        self.th.start()

    def _loop(self):
        while self.alive:
            try:
                c = os.read(self.m, 4096)
            except OSError:
                # ★ 坑：父进程若把 PTY 从端 fd 关掉（哪怕只是一瞬间），
                #   master 上读会拿到 EIO。**这里不能 break** —— 一 break 线程就死了，
                #   后面再也答不上 AT，表现为"AT 握手没走通"，很容易被误判成被测脚本的 bug。
                time.sleep(0.05)
                continue
            if not c:
                time.sleep(0.01)
                continue
            with self.lock:
                self.buf += c
                if (not self.at_replied) and (b'AT+EXIT=1' in self.buf):
                    self.at_replied = True
                    try:
                        os.write(self.m, b'\r\nOK\r\n')
                    except OSError:
                        pass
                n = self.buf.count(ACK)
                if n:
                    self.acks += n
                    self.buf = self.buf.replace(ACK, b'')
                if NAK in self.buf:
                    self.buf = self.buf.replace(NAK, b'')

    def wait_at(self, timeout):
        t0 = time.time()
        while time.time() - t0 < timeout:
            with self.lock:
                if self.at_replied:
                    return True
            time.sleep(0.05)
        return False

    def wait_acks(self, n, timeout):
        t0 = time.time()
        while time.time() - t0 < timeout:
            with self.lock:
                if self.acks >= n:
                    return True
            time.sleep(0.02)
        return False

    def step(self, data, timeout=8.0):
        """写一帧，等它的 ACK。"""
        with self.lock:
            n0 = self.acks
        try:
            os.write(self.m, data)
        except OSError:
            return False
        return self.wait_acks(n0 + 1, timeout)

    def stop(self):
        self.alive = False


def one_session(rd, payload, timeout=8.0):
    """发一个 **N=1** 的会话。返回 True 表示 BEGIN / 数据帧 / END 都被 ACK。"""
    if not rd.step(build_begin(1, 0, 0, [len(payload)]), timeout):
        return False
    if not rd.step(build_frame(1, payload), timeout):
        return False
    return rd.step(build_end(1, 1), timeout)


def scan(workdir):
    files = []
    for root, _dirs, fns in os.walk(workdir):
        for fn in fns:
            files.append(os.path.join(root, fn))
    md5s = sorted(hashlib.md5(open(f, 'rb').read()).hexdigest() for f in files)
    dirs = set(os.path.dirname(f) for f in files)
    return files, dirs, md5s


def run_case(name, script, extra, n_sessions, expect_sessions, expect_files, expect_dirs):
    script_path = os.path.join(HERE, script)
    if not os.path.exists(script_path):
        return dict(name=name, ok=False, why='缺 %s' % script_path, out='')

    master, slave = pty.openpty()
    sname = os.ttyname(slave)
    workdir = tempfile.mkdtemp(prefix='rxtest_')
    env = dict(os.environ)
    env['GLC_RADIO_DEV'] = sname
    env['PYTHONUNBUFFERED'] = '1'
    proc = subprocess.Popen([PY, script_path, '-d', workdir] + list(extra),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    # ★ 父进程**必须留着**从端 fd：一旦从端没有任何 fd 打开，master 上的读会变 EIO，
    #   而我们是在子进程还没 open 之前就起了读线程。留着它就当"占位"，不读也不写。

    rd = FakeRadio(master)
    out = ''
    try:
        if not rd.wait_at(20.0):
            proc.kill()
            out = proc.stdout.read().decode('utf-8', 'replace')
            return dict(name=name, ok=False, why='电台 AT 握手没走通', out=out)

        time.sleep(2.0)          # ★ enter_transparent() 末尾还有 1.5 s drain，早发会被它丢掉

        got = [one_session(rd, IMAGES[i]) for i in range(n_sessions)]

        try:
            proc.wait(timeout=15.0)
        except Exception:
            proc.kill()
        time.sleep(0.3)
        out = proc.stdout.read().decode('utf-8', 'replace')

        files, dirs, md5s = scan(workdir)
        want_md5 = sorted(hashlib.md5(IMAGES[i]).hexdigest()
                          for i in range(n_sessions) if expect_sessions[i])
        ok = (got == list(expect_sessions)
              and len(files) == expect_files
              and md5s == want_md5
              and (expect_dirs is None or len(dirs) == expect_dirs))
        why = ('会话结果 %s（期望 %s）｜ 文件 %d 个（期望 %d）｜ 目录 %d 个%s ｜ md5 %s'
               % (['OK' if x else '无应答' for x in got],
                  ['OK' if x else '无应答' for x in expect_sessions],
                  len(files), expect_files, len(dirs),
                  '' if expect_dirs is None else '（期望 %d）' % expect_dirs,
                  '全对' if md5s == want_md5 else '对不上: %s' % md5s))
        return dict(name=name, ok=ok, why=why, out=out)
    finally:
        rd.stop()
        for f in (master, slave):
            try:
                os.close(f)
            except OSError:
                pass
        shutil.rmtree(workdir, ignore_errors=True)


def main():
    print('=' * 72)
    print('PTY 假电台 · 常驻接收验证（不需要真电台）')
    print('  形状：3 个会话 × 每会话 1 张（= UI 队列发 3 张）')
    print('  三张 payload 长度 = %s（内容各不相同，覆盖会暴露）' % [len(p) for p in IMAGES])
    print('=' * 72)

    cases = [
        # name, script, 额外参数, 会话数, 期望每会话结果, 期望文件数, 期望目录数
        ('被测 · radio_rx_serve.py --max-sessions 3',
         'radio_rx_serve.py', ['--max-sessions', '3'], 3,
         [True, True, True], 3, 3),
        ('对照 · radio_rx_session.py（B 板现状）',
         'radio_rx_session.py', ['-t', '60'], 3,
         [True, False, False], 1, None),
    ]

    results = []
    for name, script, extra, n, exp_s, exp_f, exp_d in cases:
        print('\n---- %s ----' % name)
        r = run_case(name, script, extra, n, exp_s, exp_f, exp_d)
        results.append(r)
        for line in r.get('out', '').strip().splitlines()[-16:]:
            print('    | %s' % line)
        print('  ⇒ %s  %s' % ('✅ 符合预期' if r['ok'] else '❌ 不符合预期', r['why']))

    print('\n' + '=' * 72)
    bad = [r for r in results if not r['ok']]
    for r in results:
        print('  %s  %s' % ('✅' if r['ok'] else '❌', r['name']))
    if bad:
        print('RX_SERVE_PTY_TEST  FAIL %d/%d' % (len(bad), len(results)))
        sys.exit(1)
    print('RX_SERVE_PTY_TEST  PASS %d/%d' % (len(results), len(results)))
    sys.exit(0)


if __name__ == '__main__':
    main()
