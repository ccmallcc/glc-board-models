#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""one_small.py —— 在一个进程里跑完「小网那一段」：s2 -> 胶水 -> 3×s3 + AD

背景：`dec_seq.py` 原本给 s2/s3p1/s3p2/s3p3 各起一个进程，每个进程光
`import numpy + icraft` 就要 ~1.07 s（实测），4 次就白花 ~4.3 s。
这四个网络加起来只有 **45 MB**（s2 15.3 + s3p* 10.0×3），且 `s2+s3p1` 已被
`diag_matrix.py` 证明可稳定共存 ⇒ 合并到一个进程既省时间又安全。

**s4 仍然单独一个进程**（它逻辑地址空间 3.43 GB，必须独占）。

用法：
    python3 one_small.py <container.glc> <out_yhat.npy>
"""
import os
import sys
import time

sys.path.insert(0, '/root/glc')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np                                    # noqa: E402
import decode_board_bf16 as D                         # noqa: E402
from rans_ad_np import decode_stream, ad_backend      # noqa: E402
from icraft import xir, xrt, host_backend             # noqa: E402
from icraft.zg330backend import ZG330Backend, OcmOpt  # noqa: E402

DEV_URL = os.environ.get('GLC_DEV_URL', 'axi://zg330aiu?npu=0x40000000&dma=0x80000000')
CONSTS = os.environ.get('GLC_CONSTS', '/root/glc/consts')
SMALL = ('s2', 's3p1', 's3p2', 's3p3')

glc_path, out_npy = sys.argv[1], sys.argv[2]
T0 = time.time()

dev = xrt.Device.Open(DEV_URL)
_lv = int(os.environ.get('GLC_DEV_RESET', '1'))
if _lv:
    dev.reset(_lv)


def load(key):
    base, shapes, vids = D.SUB[key]
    net = xir.Network.CreateFromJsonFile(base + '.json')
    net.lazyLoadParamsFromFile(base + '.raw')
    tt = [t.tensorType() for t in net.inputs()]
    nv = net.view(0).setOutputsOrderByValueIds(list(vids))
    sess = xrt.Session.Create([ZG330Backend, host_backend.HostBackend], nv,
                              [dev, xrt.HostDevice.Default()])
    ZG330Backend(sess.backends[0]).ocmOptimize(OcmOpt.OPTION1)
    sess.enableTimeProfile(True)          # ★ 缺它会撞 "This Tensor is not ready!"
    sess.apply()
    return net, sess, tt, shapes


def fwd(sess, tt, shapes, arrs):
    tens = []
    for t, a in zip(tt, arrs):
        nh = D.to_nhwc(np.ascontiguousarray(a, dtype=np.float32))
        t.setShape(list(nh.shape))
        tens.append(xrt.Tensor(nh, t))
    outs = sess.forward(tens)
    res = []
    for o, shp in zip(outs, shapes):
        import io
        bio = io.BytesIO()
        o.dump(bio, 'SFB')
        res.append(D.to_nchw(np.array(np.frombuffer(bio.getvalue(),
                                                    dtype=np.float32).reshape(shp))))
    return res


nets = {}
for k in SMALL:
    t0 = time.time()
    nets[k] = load(k)
    print('  load %-5s %.2f s' % (k, time.time() - t0), flush=True)

codebook = np.load(os.path.join(CONSTS, 'z_codebook.npy'))
ysp_w = np.load(os.path.join(CONSTS, 'ysp_reduce_w.npy')).reshape(256, 768)
ysp_b = np.load(os.path.join(CONSTS, 'ysp_reduce_b.npy'))

blob = open(glc_path, 'rb').read()
q_index, dims, streams = D.parse_bitstream(blob)
(oh, ow, ph, pw, yc, yh, yw, zc, zh, zw, zcnt) = dims
z_idx = np.asarray(D.unpack_fixed_width(streams[0], zcnt, D.Z_INDEX_BITS), dtype=np.int64)
z_hat = np.ascontiguousarray(codebook[z_idx].reshape(1, zh, zw, zc)
                             .transpose(0, 3, 1, 2)).astype(np.float32)

(params,) = fwd(nets['s2'][1], nets['s2'][2], nets['s2'][3], [z_hat])
q_enc, q_dec, scales0, means0 = D.separate_prior(params)
common = D.conv1x1(params, ysp_w, ysp_b)
y_shape = (1, yc, yh, yw)
masks = D.get_mask_four_parts(*y_shape)
y_hat_so_far = np.zeros(y_shape, dtype=np.float32)

t_ad = 0.0
for k, (mask, stream) in enumerate(zip(masks, streams[1:])):
    if k == 0:
        s_, m_ = scales0, means0
    else:
        key = 's3p%d' % k
        s_, m_ = fwd(nets[key][1], nets[key][2], nets[key][3], [y_hat_so_far, common])
    cs = np.maximum(D.compact_masked(s_, mask), np.float32(D.SCALE_MIN)).astype(np.float32)
    cm = D.compact_masked(m_, mask).astype(np.float32)
    t0 = time.time()
    vals = decode_stream(stream, cs, cm)
    t_ad += time.time() - t0
    y_hat_so_far = y_hat_so_far + D.scatter_masked(vals, mask, y_shape)

y_hat = (y_hat_so_far * q_dec).astype(np.float32)
np.save(out_npy, y_hat)
print('ONE_SMALL ad=%s  ad_time=%.3f  total=%.2f' % (ad_backend(), t_ad, time.time() - T0))
