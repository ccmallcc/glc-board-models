#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单元测试_探针初值.py —— 在 PC 上验证 glc_rsd_cpu.pl_encode_cpu 的"跨帧提示"（候选 #1）

为什么要在 PC 上跑：真机只能看到"md5 一样、快了一点"，看不到内部走了哪条分支 ——
轮数、是否复用探针产物、**二进制将来真的会填充时的回退**，这些真机上都很难复现。

这里用一个**假 glc2_pack**（行为可切换 `real` / `pad`）把每条路径都跑一遍。
`pad` 模式模拟"STAGE_LEN 会被当成填充长度"的语义 —— 也就是老注释担心的那种二进制。

判据（每条都必须能失败，见每条的"反例"）：
  T0 冷启动（_SEM 未知）：从 _HMAX 起步，5 轮探针，语义判定为 real，产物正确
  T1 同一帧再编一次：1 轮探针 + 跳过定稿，产物 md5 与 T0 逐字节相同
  T2 换一张（相位0 相同、1~3 不同）：轮数 1<r<5，产物正确
  T3 提示偏大（下一帧更小）：轮数回到 5，**产物仍正确**
     ← 老注释说"从偏大初值会收敛到错误的稳定点"，本测试与真机实测都证明不会
  T4 pad 语义：必须自动识别，退回全 0 起步，且**产物与 real 模式逐字节相同**（没被填充）
  T5 残留文件：探针失败那一轮不许捡到上一帧的同名文件

用法：python3 单元测试_探针初值.py [-v]
退出码：0 全过；1 有失败
"""
import hashlib
import io
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RCDIR = os.path.join(HERE, '..', '常驻引擎')
sys.path.insert(0, RCDIR)

import glc_rsd_cpu as RC                                        # noqa: E402

FAKE = None                     # 假打包器的 .py 路径
MODE = {'sem': 'real'}          # real / pad
ZLEN = 28                       # 容器里 z 段恒 28 B（16 个 14 bit 索引），与真板一致

FAILS = []


def check(name, cond, detail=''):
    print(('  ✅ ' if cond else '  ❌ ') + name + (('   ' + detail) if detail else ''))
    if not cond:
        FAILS.append(name)


# ----------------------------------------------------------- 假 glc2_pack
FAKE_SRC = r'''# -*- coding: utf-8 -*-
"""假 glc2_pack：复刻真二进制的关键行为
   real 模式：报的永远是真值；断言（对上了才写容器）
   pad  模式：报 max(真值, STAGE_LEN) —— 用来验证我们的回退路径
"""
import json, os, re, struct, sys

d, out = sys.argv[1], sys.argv[2]
sem = os.environ.get('FAKE_SEM', 'real')
real = json.load(open(os.path.join(d, 'real.json')))
hdr = open(os.path.join(d, 'hdr.txt'), encoding='utf-8').read()
h = [int(re.search(r'^STAGE%d_LEN (\d+)' % k, hdr, re.M).group(1)) for k in range(4)]

ok = 0
for k in range(4):
    rep = real[k] if sem == 'real' else max(real[k], h[k])
    hit = (rep == h[k])
    print('  phase %d:  16384 符号 -> %5d B (参考 %d) %s' % (k, rep, h[k], '✅' if hit else '❌'))
    ok += 1 if hit else 0
    if not hit:
        break
if ok != 4:
    print('==== 失败 ====')
    sys.exit(1)
if os.environ.get('FAKE_FAIL_FINAL') and out.endswith('_rsd_final.glc'):
    print('  自产容器 生产失败（故意）')       # 用来测"定稿失败会不会捡到上一帧的残留"
    sys.exit(0)

hb = struct.pack('>4sBBH', b'GLC2', 2, 0, 0)
for v in (256, 256, 256, 256, 256, 16, 16, 256, 4, 4):
    hb += struct.pack('>I', v)
hb += struct.pack('>I', 16)                 # z_count
hb += struct.pack('>I', @ZLEN@)              # zlen
for k in range(4):
    hb += struct.pack('>I', real[k])
hb += struct.pack('>I', 0)
assert len(hb) == 76
blob = hb + bytes(@ZLEN@) + b''.join(bytes([65 + k]) * real[k] for k in range(4))
open(out, 'wb').write(blob)
print('  自产容器 %d B' % len(blob))
sys.exit(0)
'''


def fake_run(d, out):
    """替掉 _run_pack：真逻辑 = 先删旧产物 + 起子进程 + 收 stdout。这里只是换"子进程"。"""
    try:
        os.remove(out)
    except OSError:
        pass
    t0 = time.time()
    r = subprocess.run([sys.executable, FAKE, d, out], stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, universal_newlines=True,
                       encoding='utf-8', errors='replace')
    RC.STAT['pack_calls'] += 1
    return r.stdout, time.time() - t0


def fake_run_nodel(d, out):
    """对照组：**不删**旧产物（= 老代码的行为）。"""
    t0 = time.time()
    r = subprocess.run([sys.executable, FAKE, d, out], stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, universal_newlines=True,
                       encoding='utf-8', errors='replace')
    RC.STAT['pack_calls'] += 1
    return r.stdout, time.time() - t0


# ------------------------------------------------------------------ 工具
def snap():
    return {k: (v if not isinstance(v, list) else list(v)) for k, v in RC.STAT.items()}


def delta(before, after, key):
    return after[key] - before[key]


def encode(op_dir, real_lens, tag):
    """跑一帧，返回 (容器 md5, 本轮增量统计)。"""
    with open(os.path.join(op_dir, 'real.json'), 'w') as f:
        f.write(repr(list(real_lens)).replace("'", '"'))
    before = snap()
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        streams, _ = RC.pl_encode_cpu(op_dir)
    finally:
        sys.stdout = old
    after = snap()
    blob = open('/tmp/_rsd_probe.glc' if after['skip_final'] > before['skip_final']
                else '/tmp/_rsd_final.glc', 'rb').read()
    d = dict(rounds=delta(before, after, 'rounds'),
             calls=delta(before, after, 'pack_calls'),
             skip=delta(before, after, 'skip_final'),
             rounds_total=after['rounds'])
    return hashlib.md5(blob).hexdigest(), d, buf.getvalue(), streams


def fresh(name):
    d = os.path.join(tempfile.gettempdir(), 'glctest_' + name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    with open(os.path.join(d, 'hdr.txt'), 'w', encoding='utf-8') as f:
        f.write('# test hdr\n' + ''.join('STAGE%d_LEN 0\n' % k for k in range(4)))
    return d


# ------------------------------------------------------------------ 用例
def t0_t1_t2_t3(op):
    print('\n[T0] 冷启动（_SEM 未知）')
    RC._SEM = None
    RC._HINT[:] = [0, 0, 0, 0]
    md5_a, d, out, _ = encode(op, [64, 60, 52, 48], 'T0')
    if VERBOSE:
        print(out)
    check('5 轮探针', d['rounds'] == 5, 'rounds=%d' % d['rounds'])
    check('6 次起进程（5 探针 + 1 定稿）', d['calls'] == 6, 'calls=%d' % d['calls'])
    check('语义判定 real', RC._SEM == 'real', 'sem=%s' % RC._SEM)

    print('\n[T1] 同一帧再编一次（提示全中）')
    md5_b, d, out, _ = encode(op, [64, 60, 52, 48], 'T1')
    if VERBOSE:
        print(out)
    check('1 轮探针', d['rounds'] == 1, 'rounds=%d' % d['rounds'])
    check('1 次起进程（复用探针产物）', d['calls'] == 1, 'calls=%d' % d['calls'])
    check('跳过定稿', d['skip'] == 1, 'skip=%d' % d['skip'])
    check('产物 md5 与 T0 相同', md5_a == md5_b, '%s vs %s' % (md5_a[:8], md5_b[:8]))

    print('\n[T2] 换一张：相位0 相同、其余不同')
    md5_c, d, out, _ = encode(op, [64, 56, 56, 52], 'T2')
    if VERBOSE:
        print(out)
    check('轮数 1 < r < 5', 1 < d['rounds'] < 5, 'rounds=%d' % d['rounds'])
    check('没跳过定稿', d['skip'] == 0, 'skip=%d' % d['skip'])
    md5_c2, _, _, _ = encode(op, [64, 56, 56, 52], 'T2-again')
    check('T2 产物可重现（同帧两次 md5 同）', md5_c == md5_c2, '%s vs %s' % (md5_c[:8], md5_c2[:8]))
    return md5_a, md5_c


def t3_hint_too_big(op):
    print('\n[T3] 提示偏大：上一帧 [64,56,56,52]，这一帧只有 [40,40,40,40]')
    encode(op, [64, 56, 56, 52], 'T3-prep')
    md5, d, out, _ = encode(op, [40, 40, 40, 40], 'T3')
    if VERBOSE:
        print(out)
    check('轮数回到 5（提示全不中）', d['rounds'] == 5, 'rounds=%d' % d['rounds'])
    want = struct.unpack('>I', open('/tmp/_rsd_final.glc', 'rb').read()[56:60])[0]
    check('容器头里的相位0 长度 = 真值 40（没被撑成 64）', want == 40, 'header=%d' % want)


def t4_pad_semantics(op):
    print('\n[T4] pad 语义（模拟一个会把 STAGE_LEN 当填充长度的二进制）')
    md5_real, _, _, _ = encode_real_only(op)
    MODE['sem'] = 'pad'
    os.environ['FAKE_SEM'] = 'pad'
    RC._SEM = None
    RC._HINT[:] = [0, 0, 0, 0]
    md5_pad, d, out, _ = encode(op, [64, 60, 52, 48], 'T4')
    if VERBOSE:
        print(out)
    check('识别出 pad 语义', RC._SEM == 'pad', 'sem=%s' % RC._SEM)
    check('产物与 real 模式逐字节相同（没被填充）', md5_real == md5_pad,
          '%s vs %s' % (md5_real[:8], md5_pad[:8]))
    print('  （第一轮白跑 + 5 轮 = 6 轮，calls=%d）' % d['calls'])
    # pad 语义下第二帧：仍然必须正确
    md5_pad2, d2, out2, _ = encode(op, [64, 60, 52, 48], 'T4-again')
    check('pad 语义下第二帧仍与 real 产物相同', md5_pad2 == md5_real,
          '%s vs %s' % (md5_pad2[:8], md5_real[:8]))
    check('pad 语义下不冒险复用探针产物（skip=0）', d2['skip'] == 0, 'skip=%d' % d2['skip'])
    os.environ['FAKE_SEM'] = 'real'
    MODE['sem'] = 'real'


def encode_real_only(op):
    """在 real 语义下取一份"标准答案"容器 md5。"""
    old = os.environ.get('FAKE_SEM')
    os.environ['FAKE_SEM'] = 'real'
    RC._SEM = 'real'
    md5, _, _, _ = encode(op, [64, 60, 52, 48], 'real-ref')
    if old is None:
        os.environ.pop('FAKE_SEM', None)
    else:
        os.environ['FAKE_SEM'] = old
    return md5, None, None, None


def t5_stale_file(op):
    print('\n[T5] 残留文件：探针路径上先放一个垃圾文件')
    RC._HINT[:] = [0, 0, 0, 0]
    RC._SEM = 'real'
    with open('/tmp/_rsd_probe.glc', 'wb') as f:
        f.write(b'STALE-JUNK' * 100)
    md5, d, out, _ = encode(op, [72, 68, 64, 60], 'T5')
    check('产物不是那个垃圾文件', open('/tmp/_rsd_%s.glc'
          % ('probe' if d['skip'] else 'final'), 'rb').read(10) != b'STALE-JUNK',
          'skip=%d rounds=%d' % (d['skip'], d['rounds']))
    want = [struct.unpack('>I', open('/tmp/_rsd_probe.glc' if d['skip'] else '/tmp/_rsd_final.glc',
                                     'rb').read()[56 + 4 * k:60 + 4 * k])[0] for k in range(4)]
    check('容器头长度 = 真值', want == [72, 68, 64, 60], 'header=%s' % want)


def _poison(path):
    """把容器里第 1 条流的头 8 B 改成 0xFF，**头里的长度不动** —— 模拟"上一帧的残留"。"""
    blob = bytearray(open(path, 'rb').read())
    off = 76 + ZLEN
    blob[off:off + 8] = b'\xff' * 8
    with open(path, 'wb') as f:
        f.write(blob)


def t6_final_fail(op):
    """定稿那一轮"没写出文件"时，**必须报错**，不许把上一帧的 /tmp/_rsd_final.glc 当成这一帧。

    为什么这条判据要命：两个不同的画面可以有**完全相同的四个相位长度**（长度是量化过的，
    本板的实测样本里就反复出现 [64,56,56,52]）。那种情况下"容器头长度核对"这道防线
    查不出来 —— 头对得上、流是上一张的 ⇒ **静默发错图**。
    所以 `_run_pack` 每轮先删旧产物，让"文件存在"严格等于"这一轮写成功了"。

    对照组（fake_run_nodel，不删旧文件）：同一条判据必须变成"**不报错、且返回了被下毒的流**"，
    证明这条判据真的能失败。毒留的是流字节，头里的长度不动，所以头检查兜不住。
    """
    print('\n[T6] 定稿写失败：必须报错，不许捡上一帧的残留')
    A = [64, 60, 52, 48]
    RC._SEM = 'real'

    # (1) 正常编一帧，让 /tmp/_rsd_final.glc 里留着"上一帧"，然后下毒
    RC._HINT[:] = [0, 0, 0, 0]
    encode(op, A, 'T6-warm')
    check('上一帧的定稿文件确实在', os.path.exists('/tmp/_rsd_final.glc'))
    _poison('/tmp/_rsd_final.glc')

    # (2) 这一帧让打包器"不写定稿"；提示仍清 0，保证走 5 轮 + 真定稿（不复用探针产物）
    os.environ['FAKE_FAIL_FINAL'] = '1'
    RC._HINT[:] = [0, 0, 0, 0]
    raised = ''
    try:
        encode(op, A, 'T6')
    except RuntimeError as e:
        raised = str(e)[:30]
    check('报错了（没把上一帧当成本帧）', '没产出容器' in raised, raised or '没报错！')

    # (3) 对照组：不删旧文件 ⇒ 必须**不报错**、且把下毒的流交出去（= 静默发错图）
    os.environ.pop('FAKE_FAIL_FINAL', None)
    RC._HINT[:] = [0, 0, 0, 0]
    encode(op, A, 'T6-rewarm')                  # 先重新写出一份完好定稿
    _poison('/tmp/_rsd_final.glc')
    os.environ['FAKE_FAIL_FINAL'] = '1'
    RC._HINT[:] = [0, 0, 0, 0]
    RC._run_pack = fake_run_nodel
    raised2, streams2 = '', None
    try:
        _, _, _, streams2 = encode(op, A, 'T6-control')
    except RuntimeError as e:
        raised2 = str(e)[:30]
    RC._run_pack = fake_run
    os.environ.pop('FAKE_FAIL_FINAL', None)
    check('对照组不报错（判据能失败）', raised2 == '', raised2 or '没报错')
    check('对照组确实交出了上一帧的毒流（证明这个洞是真的）',
          raised2 == '' and streams2 is not None and streams2[0][:8] == b'\xff' * 8,
          '' if not raised2 else '对照组报错，无法验证')


def main():
    global FAKE, VERBOSE
    VERBOSE = '-v' in sys.argv
    tmpd = tempfile.mkdtemp(prefix='glcfake_')
    os.makedirs('/tmp', exist_ok=True)      # pl_encode_cpu 里写死了 /tmp/_rsd_*.glc
    FAKE = os.path.join(tmpd, 'fake_pack.py')
    with open(FAKE, 'w', encoding='utf-8') as f:
        f.write(FAKE_SRC.replace('@ZLEN@', str(ZLEN)))
    RC._run_pack = fake_run
    rc_dir = RC.__file__
    print('被测模块：%s' % rc_dir)
    print('假打包器：%s' % FAKE)

    for k in ('rounds', 'exact', 'skip_final', 'frames', 'pack_calls'):
        RC.STAT[k] = 0
    op = fresh('main')
    t0_t1_t2_t3(op)
    op2 = fresh('big')
    t3_hint_too_big(op2)
    op3 = fresh('pad')
    t4_pad_semantics(op3)
    op4 = fresh('stale')
    t5_stale_file(op4)
    op5 = fresh('finalfail')
    t6_final_fail(op5)

    print('\n' + ('=' * 60))
    if FAILS:
        print('失败 %d 条：%s' % (len(FAILS), ' / '.join(FAILS)))
        return 1
    print('全部通过 ✅')
    return 0


if __name__ == '__main__':
    sys.exit(main())
