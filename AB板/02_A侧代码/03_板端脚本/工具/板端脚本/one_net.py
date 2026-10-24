#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""one_net.py —— 在**独立进程**里只跑一个子图（A 侧 2026-10-12）

为什么要有它
------------
实测结论（见 57 号文档）：
  · **每个子图单独一个进程**走 Python API，输出与 icraft-run **逐位相同**（反复复现）
  · **多 session 同进程不可靠**（同一份代码连跑三次结果全不同）
  · icraft-run 跑 s4 要 **39~53 s**（`--compress` 必须开，开销很大），
    而同样的事走 Python API 只要 **9.6 s**（json 1.6 + lazy 5.4 + apply 1.3 + forward 1.33）

所以「一次只用一张网」的进程模型既**安全**又**快**：每个进程里永远只有一个 session，
用完即退（PL DDR 随进程释放）。

用法
----
    python3 one_net.py <key> <in0.npy> [in1.npy ...] <out_prefix>
输出：<out_prefix>_0.npy, <out_prefix>_1.npy ...（按 SUB[key] 的输出形状，NCHW）
"""
import io
import os
import sys
import time

sys.path.insert(0, '/root/glc')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np                                   # noqa: E402
import decode_board_bf16 as D                        # noqa: E402
from icraft import xir, xrt, host_backend            # noqa: E402
from icraft.zg330backend import ZG330Backend, OcmOpt  # noqa: E402

DEV_URL = os.environ.get('GLC_DEV_URL', 'axi://zg330aiu?npu=0x40000000&dma=0x80000000')

key = sys.argv[1]
ins = sys.argv[2:-1]
prefix = sys.argv[-1]
base, shapes, vids = D.SUB[key]

dev = xrt.Device.Open(DEV_URL)
# ★ 必须 reset：实测不做 reset 时，上一个进程残留的 PL DDR 状态会污染内存规划，
#   同一份代码连跑三次结果全不同。加上 reset 之后多次复现全部逐位正确。
_lv = int(os.environ.get('GLC_DEV_RESET', '1'))
if _lv:
    dev.reset(_lv)
# ★ 必须设等待时间：`sess.forward()` 是**异步**的，不设的话 dump 输出会撞
#   `Check failed: (this->isReady()) is false / This Tensor is not ready!`。
#   这就是 icraft-run 的 `--wait_time`（默认 10000 ms），Python API 里对应
#   `xrt.Device.setWaitTime`。
try:
    dev.setWaitTime(int(os.environ.get('GLC_WAIT_MS', '10000')))
except Exception as _e:                              # noqa: BLE001
    print('setWaitTime ✗ %s' % _e)

t0 = time.time()
net = xir.Network.CreateFromJsonFile(base + '.json')
net.lazyLoadParamsFromFile(base + '.raw')
in_tt = [t.tensorType() for t in net.inputs()]
nv = net.view(0).setOutputsOrderByValueIds(list(vids))
sess = xrt.Session.Create([ZG330Backend, host_backend.HostBackend], nv,
                          [dev, xrt.HostDevice.Default()])
ZG330Backend(sess.backends[0]).ocmOptimize(OcmOpt.OPTION1)
# ★ enableTimeProfile(True) 不只是计时：**它会让 forward 真正同步**。
#   不加它时 `sess.forward()` 立即返回，紧跟的 `t.dump()` 会撞
#   `Check failed: (this->isReady()) is false / This Tensor is not ready!`
#   （实测：光调 dev.setWaitTime(10000) 不够）。本仓所有跑通的脚本都有这一行。
sess.enableTimeProfile(True)
t1 = time.time()
sess.apply()
t2 = time.time()

tens = []
for tt, p in zip(in_tt, ins):
    a = np.load(p).astype(np.float32)
    nh = D.to_nhwc(np.ascontiguousarray(a))
    tt.setShape(list(nh.shape))
    tens.append(xrt.Tensor(nh, tt))
t3 = time.time()
outs = sess.forward(tens)
t4 = time.time()

for i, (t, shp) in enumerate(zip(outs, shapes)):
    bio = io.BytesIO()
    t.dump(bio, 'SFB')
    arr = D.to_nchw(np.array(np.frombuffer(bio.getvalue(), dtype=np.float32).reshape(shp)))
    np.save('%s_%d.npy' % (prefix, i), arr)

print('ONE_NET %-5s load=%.2f apply=%.2f fwd=%.2f total=%.2f'
      % (key, t1 - t0, t2 - t1, t4 - t3, t4 - t0))
