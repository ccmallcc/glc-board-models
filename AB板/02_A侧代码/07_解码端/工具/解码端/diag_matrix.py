#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""diag_matrix.py —— 多个 session 同进程时，到底谁和谁放一起会坏

已确认的事实：
  · 每个子图**单独**跑 Python API，输出都与 icraft-run **逐位相同**
    （s2 已证；s3p1 输入顺序已证；s4 已证）
  · 任意两个以上同进程 → 出错
  · 实测到物理地址重叠：s2 的 INPUT/OUTPUT 落在 s3p1 的 WEIGHT 区间内
    （但把它们各自 userReuseSegment 钉到独立 chunk 后，输出**仍然**不对）

本脚本用**固定的已知输入 + 硬编码的参考值**逐个组合验证，画出「组合 × 正确性」矩阵。

用法：python3 diag_matrix.py s2,s3p1 [--pin]
"""
import io
import json
import os
import sys
import time

sys.path.insert(0, '/root/glc')
sys.path.insert(0, '/root/tp5603_drv/glcdec')

import numpy as np                                   # noqa: E402
import decode_board_bf16 as D                        # noqa: E402
from icraft import xir, xrt, host_backend            # noqa: E402
from icraft.zg330backend import ZG330Backend, OcmOpt, SegmentType  # noqa: E402

DEV_URL = 'axi://zg330aiu?npu=0x40000000&dma=0x80000000'
MAN = '/root/glc/seg_manifest.json'
SEGS = ('WEIGHT', 'INSTR', 'FTMP', 'INPUT', 'OUTPUT')
KEEP = []

# ---- 固定输入（与之前各次实验完全一致）
Z_IN = np.random.RandomState(0).randn(1, 256, 4, 4).astype(np.float32)
S3_A = np.zeros((1, 256, 16, 16), np.float32)
S3_B = np.ones((1, 256, 16, 16), np.float32)
_z = np.load('/root/base1.npz')
Y_IN, X_REF = _z['y_hat'], _z['x_hat']

# ---- 参考值（icraft-run 实测，见各 diag 日志）
REF = {
    's2':   [dict(mn=-1.01660, mx=1.95605, mean=0.43604)],
    's3p1': [dict(mn=-0.37402, mx=1.48438, mean=0.17320),
             dict(mn=-0.64307, mx=1.48438, mean=0.06884)],
}


def short(e):
    m = [l for l in str(e).splitlines() if 'xception info' in l or 'Check failed' in l]
    return m[-1].strip()[:100] if m else str(e)[:100]


class Net(object):
    def __init__(self, key, dev, man, pin):
        base, shapes, vids = D.SUB[key]
        self.key, self.shapes, self.vids = key, shapes, vids
        self.net = xir.Network.CreateFromJsonFile(base + '.json')
        self.net.lazyLoadParamsFromFile(base + '.raw')
        self.in_tt = [t.tensorType() for t in self.net.inputs()]
        nv = self.net.view(0).setOutputsOrderByValueIds(list(vids))
        self.sess = xrt.Session.Create([ZG330Backend, host_backend.HostBackend], nv,
                                       [dev, xrt.HostDevice.Default()])
        be = ZG330Backend(self.sess.backends[0])
        be.ocmOptimize(OcmOpt.OPTION1)
        self.pinned = []
        if pin:
            region = dev.getMemRegion('plddr')
            for nm in SEGS:
                sz = int(man.get(key, {}).get(nm, 0))
                if sz <= 0:
                    continue
                try:
                    c = region.malloc(sz, False, 4096)
                    KEEP.append(c)
                    be.userReuseSegment(c, getattr(SegmentType, nm))
                    self.pinned.append(nm)
                except Exception as e:                            # noqa: BLE001
                    print('    [%s] 钉 %s ✗ %s' % (key, nm, short(e)), flush=True)
        self.sess.enableTimeProfile(True)
        t0 = time.time()
        self.sess.apply()
        self.apply_s = time.time() - t0

    def forward(self, arrays):
        tens = []
        for tt, a in zip(self.in_tt, arrays):
            nh = D.to_nhwc(np.ascontiguousarray(a, dtype=np.float32))
            tt.setShape(list(nh.shape))
            tens.append(xrt.Tensor(nh, tt))
        outs = self.sess.forward(tens)
        res = []
        for t, shp in zip(outs, self.shapes):
            bio = io.BytesIO()
            t.dump(bio, 'SFB')
            res.append(D.to_nchw(np.array(np.frombuffer(bio.getvalue(),
                                                        dtype=np.float32).reshape(shp))))
        return res


def check(key, out):
    if key == 's4':
        ok = np.array_equal(out[0], X_REF)
        d = float(np.nanmax(np.abs(out[0].astype(np.float64) - X_REF.astype(np.float64))))
        inf = int(np.isinf(out[0]).sum())
        return ok, 'x_hat  最大差=%.6g inf=%d' % (d, inf)
    refs = REF[key]
    res = []
    ok = True
    for o, r in zip(out, refs):
        a = o.astype(np.float64)
        good = (abs(a.min() - r['mn']) < 1e-3 and abs(a.max() - r['mx']) < 1e-3
                and abs(a.mean() - r['mean']) < 1e-3)
        ok = ok and good
        res.append('%s(%.4f/%.4f/%.4f)' % ('✓' if good else '✗', a.min(), a.max(), a.mean()))
    return ok, ' '.join(res)


def main():
    keys = sys.argv[1].split(',')
    pin = '--pin' in sys.argv
    man = json.load(open(MAN)) if (pin and os.path.exists(MAN)) else {}
    print('=' * 88)
    print('  组合 = %s   pin=%s' % (keys, pin))
    print('=' * 88)
    dev = xrt.Device.Open(DEV_URL)
    nets = {}
    for k in keys:
        nets[k] = Net(k, dev, man, pin)
        print('  [载入 %-5s] apply %.2f s  钉住: %s' % (k, nets[k].apply_s,
                                                     ','.join(nets[k].pinned) or '无'), flush=True)
    print('  --- 逐个 forward（全在同一个进程里）---', flush=True)
    allok = True
    for k in keys:
        ins = {'s2': [Z_IN], 's4': [Y_IN]}.get(k, [S3_A, S3_B])
        out = nets[k].forward(ins)
        ok, msg = check(k, out)
        allok = allok and ok
        print('  %-5s %s  %s' % (k, '✓ 与单独跑一致' if ok else '✗ 不一致', msg), flush=True)
    print('  ⇒ 组合 %s : %s' % (keys, '全部正确 ✓' if allok else '有错 ✗'))
    print('DIAG_MATRIX_DONE')


if __name__ == '__main__':
    main()
