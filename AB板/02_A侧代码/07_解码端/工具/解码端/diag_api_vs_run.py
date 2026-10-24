#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""diag_api_vs_run.py —— 诊断「Python API 常驻 session」与「icraft-run」结果不一致

背景（2026-10-12 实测）：
  · decode_board_bf16.py + GLC_COMPRESS=1 解 img1.glc  → PNG 124468 B 正常，s4 耗时 ~40 s
  · glc_dec_resident.py（Python API 常驻）解同一容器   → PNG 758 B 全白，s4 耗时 0.035 s
  · 对比 npz：y_hat 最大差 1.98；x_hat 全 inf

本脚本把两条路径隔离比较：
  s2   —— 小网（15 MB），不撞 2 GB；同样输入，icraft-run vs API
  s4   —— 大网（452 MB，Network size 3.43 GB > 2 GB）；API 用 base1.npz 的 y_hat
          作输入，与 base1.npz 的 x_hat（icraft-run + --compress 的已知正确输出）比
  s4run—— 同一个 y_hat 走 icraft-run（+--compress），确认 baseline 可复现

用法：
  python3 diag_api_vs_run.py s2
  python3 diag_api_vs_run.py s4      [ocm|noocm|noetm|noocm_noetm]
  python3 diag_api_vs_run.py s4run
每个子命令都在**独立进程**里跑（PL DDR 要进程退出才释放）。
"""
import io
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, '/root/glc')
sys.path.insert(0, '/root/tp5603_drv/glcdec')

import numpy as np                      # noqa: E402
import decode_board_bf16 as D           # noqa: E402
from icraft import xir, xrt, host_backend                              # noqa: E402
from icraft.zg330backend import ZG330Backend, OcmOpt                   # noqa: E402

DEV_URL = 'axi://zg330aiu?npu=0x40000000&dma=0x80000000'
RUN = '/root/tp5603_drv/diag_run'
ICRAFT = os.environ.get('GLC_ICRAFT', '/usr/bin/icraft-run')
BASE_NPZ = '/root/base1.npz'


def run_icraft(key, inputs, compress=True, tag='run'):
    base, shapes, vids = D.SUB[key]
    run = os.path.join(RUN, tag)
    shutil.rmtree(run, ignore_errors=True)
    os.makedirs(run)
    ins = []
    for i, t in enumerate(inputs):
        fp = os.path.join(run, 'in%d.ftmp' % i)
        D.to_nhwc(np.ascontiguousarray(t, dtype=np.float32)).tofile(fp)
        ins.append(fp)
    argv = [ICRAFT, '--json', base + '.json', '--raw', base + '.raw',
            '--input', ';'.join(ins),
            '--backends', 'ZG330,axi://zg330aiu;Host',
            '--log_path', os.path.join(run, 'log'),
            '--dump_format', 'SFB',
            '--dump_ftmp', ','.join(str(v) for v in vids)]
    if compress:
        argv.append('--compress')
    t0 = time.time()
    p = subprocess.run(argv, cwd=run, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    dt = time.time() - t0
    outs = []
    for v, shp in zip(vids, shapes):
        fp = os.path.join(run, 'log', os.path.basename(base).replace('_ZG', ''),
                          'ftmpSFB', '%d.ftmp' % v)
        if not os.path.exists(fp):
            raise SystemExit('%s 没产出 %d（rc=%d）\n%s'
                             % (key, v, p.returncode, p.stdout.decode('utf-8', 'replace')[-900:]))
        outs.append(D.to_nchw(np.fromfile(fp, dtype=np.float32).reshape(shp)))
    return outs, dt


class ApiNet(object):
    def __init__(self, key, dev, ocm=True, etm=True):
        base, shapes, vids = D.SUB[key]
        self.out_shapes = shapes
        self.key = key
        t0 = time.time()
        self.net = xir.Network.CreateFromJsonFile(base + '.json')
        self.net.lazyLoadParamsFromFile(base + '.raw')
        self.in_tt = [t.tensorType() for t in self.net.inputs()]
        nv = self.net.view(0).setOutputsOrderByValueIds(list(vids))
        self.sess = xrt.Session.Create([ZG330Backend, host_backend.HostBackend], nv,
                                       [dev, xrt.HostDevice.Default()])
        be = ZG330Backend(self.sess.backends[0])
        if not etm:
            be.disableEtmOptimize()
            print('    disableEtmOptimize() 已调用; is_etmOptimize =', be.is_etmOptimize)
        if ocm:
            be.ocmOptimize(OcmOpt.OPTION1)
        print('    ocm=%s etm=%s  载入 %.2f s' % (ocm, etm, time.time() - t0), flush=True)
        self.sess.enableTimeProfile(True)
        t0 = time.time()
        self.sess.apply()
        print('    apply %.2f s' % (time.time() - t0), flush=True)

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
        for t, shp in zip(outs, self.out_shapes):
            bio = io.BytesIO()
            t.dump(bio, 'SFB')
            res.append(D.to_nchw(np.array(np.frombuffer(bio.getvalue(),
                                                        dtype=np.float32).reshape(shp))))
        return res, dt


def stat(name, a):
    a = np.asarray(a, dtype=np.float64)
    print('    %-14s min=%12.5f max=%12.5f mean=%12.5f  inf=%d nan=%d'
          % (name, np.nanmin(a), np.nanmax(a), np.nanmean(a),
             int(np.isinf(a).sum()), int(np.isnan(a).sum())))


def cmp2(tag, A, B):
    A = np.asarray(A, dtype=np.float64)
    B = np.asarray(B, dtype=np.float64)
    with np.errstate(invalid='ignore'):
        d = np.abs(A - B)
    bad = int(np.isnan(d).sum() + np.isinf(d).sum())
    print('    %s: 逐位相等=%s  最大绝对差=%s  非有限差个数=%d'
          % (tag, np.array_equal(A, B), ('%.6g' % np.nanmax(d)) if d.size else 'n/a', bad))


def case_s2():
    print('=' * 84)
    print('  case s2：小网（15 MB），icraft-run(无 --compress) vs Python API')
    print('=' * 84)
    rs = np.random.RandomState(0)
    z = rs.randn(1, 256, 4, 4).astype(np.float32)
    print('  输入 z: (1,256,4,4)  min=%.4f max=%.4f' % (z.min(), z.max()))

    o, dt = run_icraft('s2', [z], compress=False, tag='s2run')
    print('  [icraft-run] %.2f s' % dt)
    stat('run.params', o[0])

    dev = xrt.Device.Open(DEV_URL)
    api = ApiNet('s2', dev)
    oa, dt = api.forward([z])
    print('  [API] forward %.3f s' % dt)
    stat('api.params', oa[0])
    cmp2('s2 params', o[0], oa[0])


def case_s4(variant='ocm'):
    print('=' * 84)
    print('  case s4：大网（452 MB, Network size 3.43 GB > 2 GB）  variant=%s' % variant)
    print('=' * 84)
    z = np.load(BASE_NPZ)
    y = z['y_hat']
    xr_ = z['x_hat']
    print('  输入 y_hat（来自 icraft-run 的已知正确结果）: %s' % (y.shape,))
    stat('y_hat', y)
    stat('期望 x_hat', xr_)

    dev = xrt.Device.Open(DEV_URL)
    api = ApiNet('s4', dev, ocm=('noocm' not in variant), etm=('noetm' not in variant))
    oa, dt = api.forward([y])
    print('  [API] forward %.3f s' % dt)
    stat('api.x_hat', oa[0])
    cmp2('s4 x_hat (API vs icraft-run)', xr_, oa[0])


def case_s4run():
    print('=' * 84)
    print('  case s4run：同一个 y_hat 走 icraft-run + --compress（baseline 可复现性）')
    print('=' * 84)
    z = np.load(BASE_NPZ)
    y, xr_ = z['y_hat'], z['x_hat']
    o, dt = run_icraft('s4', [y], compress=True, tag='s4run')
    print('  [icraft-run] %.2f s' % dt)
    stat('run.x_hat', o[0])
    cmp2('s4 x_hat (run vs base1.npz)', xr_, o[0])


if __name__ == '__main__':
    what = sys.argv[1] if len(sys.argv) > 1 else 's2'
    if what == 's2':
        case_s2()
    elif what == 's4':
        case_s4(sys.argv[2] if len(sys.argv) > 2 else 'ocm')
    elif what == 's4run':
        case_s4run()
    else:
        raise SystemExit('未知 case: ' + what)
    print('DIAG_DONE')
