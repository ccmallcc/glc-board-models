#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""diag_s3_order.py —— s3 的两个输入，Python API 的顺序和 icraft-run 一致吗？

动机：
  s3 子图有**两个同形状输入** (1,16,16,256)，而 decode_board_bf16.py 是按
  `--input 'in0.ftmp;in1.ftmp'`（in0=y_hat_so_far, in1=common）喂的。
  Python API 走的是 `net.inputs()` 的顺序 —— **没人验证过这两者是否一致**。
  之前所有共存实验给 s3 喂的都是 `[同一个随机数组]*2`，顺序错了也看不出来。

判据：
  用两个**可区分**的输入 A=全 0、B=全 1：
    · icraft-run(A;B)      -> R
    · API [A,B]            -> X_ab
    · API [B,A]            -> X_ba
    X_ab == R  ⇒ net.inputs() 顺序 == --input 顺序 ✓
    X_ba == R  ⇒ net.inputs() 顺序是反的 ✗（这就是常驻引擎 y_hat 差 1.98 的根因）

只读，不改任何东西。
"""
import io
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, '/root/glc')
sys.path.insert(0, '/root/tp5603_drv/glcdec')

import numpy as np                                   # noqa: E402
import decode_board_bf16 as D                        # noqa: E402
from icraft import xir, xrt, host_backend            # noqa: E402
from icraft.zg330backend import ZG330Backend, OcmOpt # noqa: E402

DEV_URL = 'axi://zg330aiu?npu=0x40000000&dma=0x80000000'
ICRAFT = '/usr/bin/icraft-run'
RUN = '/root/tp5603_drv/diag_s3'
KEY = 's3p1'


def stat(tag, a):
    a = np.asarray(a, dtype=np.float64)
    print('  %-16s min=%12.5f max=%12.5f mean=%12.5f inf=%d'
          % (tag, np.nanmin(a), np.nanmax(a), np.nanmean(a), int(np.isinf(a).sum())), flush=True)


base, shapes, vids = D.SUB[KEY]
A = np.zeros((1, 256, 16, 16), np.float32)
B = np.ones((1, 256, 16, 16), np.float32)

# ---------------- 1) icraft-run 参考
shutil.rmtree(RUN, ignore_errors=True)
os.makedirs(RUN)
ins = []
for i, t in enumerate([A, B]):
    fp = os.path.join(RUN, 'in%d.ftmp' % i)
    D.to_nhwc(t).tofile(fp)
    ins.append(fp)
argv = [ICRAFT, '--json', base + '.json', '--raw', base + '.raw',
        '--input', ';'.join(ins), '--backends', 'ZG330,axi://zg330aiu;Host',
        '--log_path', os.path.join(RUN, 'log'), '--dump_format', 'SFB',
        '--dump_ftmp', ','.join(str(v) for v in vids)]
t0 = time.time()
p = subprocess.run(argv, cwd=RUN, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
print('icraft-run %.2f s rc=%d' % (time.time() - t0, p.returncode), flush=True)
R = []
for v, shp in zip(vids, shapes):
    fp = os.path.join(RUN, 'log', os.path.basename(base).replace('_ZG', ''),
                      'ftmpSFB', '%d.ftmp' % v)
    if not os.path.exists(fp):
        raise SystemExit('没产出 %d\n%s' % (v, p.stdout.decode('utf-8', 'replace')[-800:]))
    R.append(D.to_nchw(np.fromfile(fp, dtype=np.float32).reshape(shp)))
for i, r in enumerate(R):
    stat('icraft-run out%d' % i, r)

# ---------------- 2) Python API
dev = xrt.Device.Open(DEV_URL)
net = xir.Network.CreateFromJsonFile(base + '.json')
net.lazyLoadParamsFromFile(base + '.raw')
in_names = []
in_tt = []
for ten in net.inputs():
    try:
        in_names.append(ten.name)
    except Exception:                                # noqa: BLE001
        in_names.append('?')
    in_tt.append(ten.tensorType())
print('net.inputs() 顺序 =', in_names, flush=True)
nv = net.view(0).setOutputsOrderByValueIds(list(vids))
sess = xrt.Session.Create([ZG330Backend, host_backend.HostBackend], nv,
                          [dev, xrt.HostDevice.Default()])
ZG330Backend(sess.backends[0]).ocmOptimize(OcmOpt.OPTION1)
sess.enableTimeProfile(True)
sess.apply()


def fwd(arrs):
    tens = []
    for tt, a in zip(in_tt, arrs):
        nh = D.to_nhwc(np.ascontiguousarray(a, dtype=np.float32))
        tt.setShape(list(nh.shape))
        tens.append(xrt.Tensor(nh, tt))
    outs = sess.forward(tens)
    res = []
    for t, shp in zip(outs, shapes):
        bio = io.BytesIO()
        t.dump(bio, 'SFB')
        res.append(D.to_nchw(np.array(np.frombuffer(bio.getvalue(),
                                                    dtype=np.float32).reshape(shp))))
    return res


Xab = fwd([A, B])
for i, r in enumerate(Xab):
    stat('API [A,B] out%d' % i, r)
Xba = fwd([B, A])
for i, r in enumerate(Xba):
    stat('API [B,A] out%d' % i, r)

print()
for i in range(len(R)):
    d_ab = np.abs(Xab[i] - R[i]).max()
    d_ba = np.abs(Xba[i] - R[i]).max()
    print('  out%d:  API[A,B] vs icraft-run 最大差 = %.6g   %s'
          % (i, d_ab, '✓ 顺序一致' if d_ab < 1e-4 else '✗'))
    print('        API[B,A] vs icraft-run 最大差 = %.6g   %s'
          % (i, d_ba, '★ 顺序是反的！' if d_ba < 1e-4 else '✗'))
print('DIAG_S3_ORDER_DONE')
