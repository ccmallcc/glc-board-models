#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""diag_s4_coexist.py —— 5 个 session 同进程时，s4 什么时候被搞坏

已确认（diag_s4_async.py）：
  · s4 单独一个 session 走 Python API → 输出与 icraft-run 逐位相同（forward 1.333 s）
  · BuyiBackend 暴露了 compressFtmp / getDeploySize / speedMode

但 glc_dec_resident.py 里 5 个 session 同进程时，s4 输出全 inf、forward 只 0.035 s。
本脚本按**不同加载顺序**重现，定位是「顺序/PL DDR 抢占」还是别的。

用法：
  python3 diag_s4_coexist.py s4_first      # 先 s4，再 s2/s3x3
  python3 diag_s4_coexist.py small_first   # 先 s2/s3x3，再 s4（= 常驻引擎原顺序）
  python3 diag_s4_coexist.py s4_only       # 只 s4（对照）

判据：forward 完立刻 dump，与 base1.npz 的 x_hat 比。期望 min=-1.0625 max=1.0625 inf=0。
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
KEYS = ['s2', 's3p1', 's3p2', 's3p3', 's4']


class Net(object):
    def __init__(self, key, dev):
        base, shapes, vids = D.SUB[key]
        self.key = key
        self.shapes = shapes
        self.vids = vids
        t0 = time.time()
        self.net = xir.Network.CreateFromJsonFile(base + '.json')
        self.net.lazyLoadParamsFromFile(base + '.raw')
        self.in_tt = [t.tensorType() for t in self.net.inputs()]
        nv = self.net.view(0).setOutputsOrderByValueIds(list(vids))
        self.sess = xrt.Session.Create([ZG330Backend, host_backend.HostBackend], nv,
                                       [dev, xrt.HostDevice.Default()])
        ZG330Backend(self.sess.backends[0]).ocmOptimize(OcmOpt.OPTION1)
        self.sess.enableTimeProfile(True)
        t1 = time.time()
        self.sess.apply()
        print('    [%s] 载入 %.2f + apply %.2f = %.2f s'
              % (key, t1 - t0, time.time() - t1, time.time() - t0), flush=True)

    def forward(self, arrays):
        tens = []
        for tt, a in zip(self.in_tt, arrays):
            nh = D.to_nhwc(np.ascontiguousarray(a, dtype=np.float32))
            tt.setShape(list(nh.shape))
            tens.append(xrt.Tensor(nh, tt))
        t0 = time.time()
        outs = self.sess.forward(tens)
        dt = time.time() - t0
        res = []
        for t, shp in zip(outs, self.shapes):
            bio = io.BytesIO()
            t.dump(bio, 'SFB')
            res.append(D.to_nchw(np.array(np.frombuffer(bio.getvalue(),
                                                        dtype=np.float32).reshape(shp))))
        return res, dt


def stat(tag, a):
    a = np.asarray(a, dtype=np.float64)
    print('  %-14s min=%12.5f max=%12.5f mean=%12.5f inf=%d'
          % (tag, np.nanmin(a), np.nanmax(a), np.nanmean(a), int(np.isinf(a).sum())), flush=True)


def main(mode):
    z = np.load('/root/base1.npz')
    y_hat, x_ref = z['y_hat'], z['x_hat']
    print('=' * 84)
    print('  mode = %s' % mode)
    print('=' * 84)
    stat('expect', x_ref)

    if mode == 's4_first':
        order = ['s4', 's2', 's3p1', 's3p2', 's3p3']
    elif mode == 'small_first':
        order = ['s2', 's3p1', 's3p2', 's3p3', 's4']
    elif mode == 's4_only':
        order = ['s4']
    else:
        raise SystemExit('未知 mode')

    dev = xrt.Device.Open(DEV_URL)
    nets = {}
    t_all = time.time()
    for k in order:
        nets[k] = Net(k, dev)
    print('  全部载入 %.2f s' % (time.time() - t_all), flush=True)

    if 's4' not in nets:
        return
    # 每个已载入的 session 都跑一次 forward，看谁先坏
    for k in order:
        n = nets[k]
        if k == 's4':
            ins = [y_hat]
        elif k == 's2':
            r = np.random.RandomState(0)
            ins = [r.randn(1, 256, 4, 4).astype(np.float32)]
        else:
            r = np.random.RandomState(1)
            ins = [r.randn(1, 256, 16, 16).astype(np.float32)] * 2
        o, dt = n.forward(ins)
        print('  [forward %-5s] %.3f s' % (k, dt), flush=True)
        if k == 's4':
            stat('  实际 x_hat', o[0])
            d = np.abs(o[0].astype(np.float64) - x_ref.astype(np.float64))
            print('   与 expect 逐位相等=%s  最大差=%.6g  非有限=%d'
                  % (np.array_equal(o[0], x_ref), np.nanmax(d) if not np.isnan(d).all() else -1,
                     int(np.isnan(d).sum() + np.isinf(d).sum())), flush=True)
        else:
            stat('  %s out0' % k, o[0])
    print('DIAG_COEXIST_DONE')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'small_first')
