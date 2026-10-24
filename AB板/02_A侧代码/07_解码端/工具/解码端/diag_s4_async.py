#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""diag_s4_async.py —— s4 走 Python API 得到 inf，到底是「异步没等」还是「超 2GB 跑不了」

两个假设：
  H1 异步：sess.forward() 立即返回，NPU 还在算，dump 到的是未完成/未初始化的缓冲
           （icraft-run 有 --wait_time 默认 10000 ms；xrt.Device 有 setWaitTime）
  H2 超限：s4 整图 bf16 的 Network size 3.43 GB > PL DDR 2 GB，内存规划重叠 → 结果无意义
           （icraft-run 靠 --compress 把 ftmp 压下来才跑得动，而 Python 侧没绑 compressFtmp）

判据：
  · 立刻 dump  A；sleep 60 s 后再 dump B
      A != B                        ⇒ H1 成立（还在算）
      A == B == inf                 ⇒ 更像是 H2
  · 再 dev.setWaitTime(10000) 重跑一次 forward，dump C
      C ≈ base1.npz 的 x_hat        ⇒ H1 就是根因，且已解决

输入用 base1.npz 里的 y_hat（icraft-run + --compress 的已知正确中间量），
期望输出用 base1.npz 的 x_hat。只读，不写真东西。
"""
import io
import os
import sys
import time

sys.path.insert(0, '/root/glc')
sys.path.insert(0, '/root/tp5603_drv/glcdec')

import numpy as np                                   # noqa: E402
import decode_board_bf16 as D                        # noqa: E402
from icraft import xir, xrt, host_backend            # noqa: E402
from icraft.zg330backend import ZG330Backend, OcmOpt # noqa: E402

DEV_URL = 'axi://zg330aiu?npu=0x40000000&dma=0x80000000'
BASE = '/root/glc/models/s4_bf16_test/s4_gs_generator_ZG'
VID = [4115]
OUT_SHAPE = (1, 256, 256, 3)


def dump_tensor(t):
    bio = io.BytesIO()
    t.dump(bio, 'SFB')
    return D.to_nchw(np.array(np.frombuffer(bio.getvalue(), dtype=np.float32).reshape(OUT_SHAPE)))


def stat(tag, a):
    a = np.asarray(a, dtype=np.float64)
    print('  %-12s min=%12.5f max=%12.5f mean=%12.5f inf=%d'
          % (tag, np.nanmin(a), np.nanmax(a), np.nanmean(a), int(np.isinf(a).sum())), flush=True)


z = np.load('/root/base1.npz')
y_hat, x_ref = z['y_hat'], z['x_hat']
print('参考 x_hat:'); stat('expect', x_ref)

# ---- BuyiBackend 有没有 compressFtmp
try:
    from icraft import buyibackend as bb
    print('BuyiBackend 方法:', [m for m in dir(bb.BuyiBackend) if not m.startswith('_')])
except Exception as e:                                # noqa: BLE001
    print('buyibackend 导入失败:', e)

dev = xrt.Device.Open(DEV_URL)
try:
    print('Device.setWaitTime 默认？(绑定存在:', hasattr(dev, 'setWaitTime'), ')')
except Exception as e:                                # noqa: BLE001
    print(e)

t0 = time.time()
net = xir.Network.CreateFromJsonFile(BASE + '.json')
net.lazyLoadParamsFromFile(BASE + '.raw')
in_tt = [t.tensorType() for t in net.inputs()]
nv = net.view(0).setOutputsOrderByValueIds(VID)
sess = xrt.Session.Create([ZG330Backend, host_backend.HostBackend], nv,
                          [dev, xrt.HostDevice.Default()])
be = ZG330Backend(sess.backends[0])
be.ocmOptimize(OcmOpt.OPTION1)
sess.enableTimeProfile(True)
print('载入 %.2f s，apply ...' % (time.time() - t0), flush=True)
t0 = time.time()
sess.apply()
print('apply %.2f s' % (time.time() - t0), flush=True)


def forward():
    tens = []
    for tt, a in zip(in_tt, [y_hat]):
        nh = D.to_nhwc(np.ascontiguousarray(a, dtype=np.float32))
        tt.setShape(list(nh.shape))
        tens.append(xrt.Tensor(nh, tt))
    t0 = time.time()
    outs = sess.forward(tens)
    dt = time.time() - t0
    return outs[0], dt


# ---------- 第一轮：forward 后立刻 dump（A），sleep 后 dump（B）
o, dt = forward()
print('\n[1] forward %.3f s，立刻 dump' % dt, flush=True)
A = dump_tensor(o)
stat('A 立刻', A)

print('[1] sleep 60 s 后再 dump 同一个 tensor ...', flush=True)
time.sleep(60)
B = dump_tensor(o)
stat('B 60s后', B)
print('  A == B ?', np.array_equal(A, B))

# ---------- 第二轮：setWaitTime 之后 forward
try:
    dev.setWaitTime(10000)
    print('\n[2] dev.setWaitTime(10000) OK', flush=True)
except Exception as e:                                # noqa: BLE001
    print('\n[2] setWaitTime 失败:', e, flush=True)

o2, dt2 = forward()
print('[2] forward %.3f s' % dt2, flush=True)
C = dump_tensor(o2)
stat('C setWait', C)
print('  C == expect ?', np.array_equal(C, x_ref))

# ---------- 第三轮：forward 后再取 timeProfile / totalTime 强制同步
try:
    tt = sess.totalTime()
    print('\n[3] sess.totalTime() =', tt, flush=True)
except Exception as e:                                # noqa: BLE001
    print('\n[3] totalTime 失败:', e, flush=True)
try:
    tpr = sess.timeProfileResults()
    print('[3] timeProfileResults 条数 =', len(tpr), flush=True)
    for r in list(tpr)[:6]:
        print('     ', r, flush=True)
except Exception as e:                                # noqa: BLE001
    print('[3] timeProfileResults 失败:', e, flush=True)

D2 = dump_tensor(o2)
stat('D 同步后', D2)
print('  D == expect ?', np.array_equal(D2, x_ref))
print('DIAG_ASYNC_DONE')
