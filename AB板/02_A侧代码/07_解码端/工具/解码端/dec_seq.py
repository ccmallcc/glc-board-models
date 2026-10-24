#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""dec_seq.py —— B 板解码驱动：**一子图一进程、顺序执行**（A 侧 2026-10-12）

设计依据（57 号文档，全部为板上实测）：
  · 每个子图单独一个进程走 Python API ⇒ 输出与 icraft-run **逐位相同**（反复复现）
  · 多 session 同进程 ⇒ **不可靠**（同代码连跑三次结果全不同）
  · icraft-run 跑 s4 要 39~53 s，Python API 只要 9.6 s
⇒ 本驱动**每个子图 fork 一个 `one_net.py` 进程**，前一个退出后才起下一个，
   任何时刻系统里只有一个 icraft session。安全 + 比 icraft-run 快。

另：AD 熵解码走 `rans_ad_np`（已打补丁接上 C 版 rans_fast.so，逐位等价，3.45 s → 0.063 s）。

用法
----
    python3 dec_seq.py <container.glc> [--out x.png] [--repeat N] [--no-s4]
"""
import argparse
import os
import subprocess
import sys
import time

sys.path.insert(0, '/root/glc')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np                                   # noqa: E402
import decode_board_bf16 as D                        # noqa: E402
from rans_ad_np import decode_stream, ad_backend     # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
TMP = os.environ.get('GLC_SEQ_TMP', '/root/glc/seq_tmp')
CONSTS = os.environ.get('GLC_CONSTS', '/root/glc/consts')

SMALL_ONE_PROC = bool(os.environ.get('GLC_SMALL_ONE_PROC'))
# ⚠️ GLC_SMALL_ONE_PROC=1 是**已验证的否定结果**，默认关闭，不要开：
#    把 s2+s3p1+s3p2+s3p3（4 个 session，合计仅 45 MB）合并进一个进程后，
#    输出**确定性错误**（连跑 4 次 md5 全为 5c237843…，而基线是 2486e8e1…）。
#    ⇒ 「一进程一 session」不是保守选择，而是**必要条件**。
os.makedirs(TMP, exist_ok=True)
STAGE = {}
_N = [0]


def one(key, inputs, t):
    """把 inputs 存盘 -> fork one_net.py -> 读回输出。返回 (outs, 墙钟秒)。"""
    os.makedirs(TMP, exist_ok=True)
    _N[0] += 1
    tag = '%s_%d' % (key, _N[0])
    paths = []
    for i, a in enumerate(inputs):
        p = os.path.join(TMP, '%s_in%d.npy' % (tag, i))
        np.save(p, np.ascontiguousarray(a, dtype=np.float32))
        paths.append(p)
    pre = os.path.join(TMP, '%s_out' % tag)
    t0 = time.time()
    r = subprocess.run([PY, os.path.join(HERE, 'one_net.py'), key] + paths + [pre],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    dt = time.time() - t0
    if r.returncode != 0:
        raise SystemExit('%s 子进程失败 rc=%d\n%s'
                         % (key, r.returncode, r.stdout.decode('utf-8', 'replace')[-1500:]))
    line = [l for l in r.stdout.decode('utf-8', 'replace').splitlines() if 'ONE_NET' in l]
    if t is not None:
        t[key] = t.get(key, 0.0) + dt
    return [np.load('%s_%d.npy' % (pre, i)) for i in range(len(D.SUB[key][1]))], dt


def decode_one(glc_path, consts, args):
    codebook, ysp_w, ysp_b = consts
    blob = open(glc_path, 'rb').read()
    q_index, dims, streams = D.parse_bitstream(blob)
    (oh, ow, ph, pw, yc, yh, yw, zc, zh, zw, zcnt) = dims
    z_payload, y_streams = streams[0], streams[1:]
    t = {}
    T0 = time.time()

    z_idx = np.asarray(D.unpack_fixed_width(z_payload, zcnt, D.Z_INDEX_BITS), dtype=np.int64)
    z_hat = np.ascontiguousarray(codebook[z_idx].reshape(1, zh, zw, zc)
                                 .transpose(0, 3, 1, 2)).astype(np.float32)

    if SMALL_ONE_PROC:
        # ★ 四个小网（合计 45 MB）合并到一个进程：省 3 次进程启动 + 3 次 import
        t0 = time.time()
        r = subprocess.run([PY, os.path.join(HERE, 'one_small.py'), glc_path,
                            os.path.join(TMP, 'y_hat.npy')],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if r.returncode != 0:
            raise SystemExit('one_small.py 失败 rc=%d\n%s'
                             % (r.returncode, r.stdout.decode('utf-8', 'replace')[-1500:]))
        t['small'] = time.time() - t0
        y_hat = np.load(os.path.join(TMP, 'y_hat.npy'))
        t['ad'] = 0.0
    else:
        (params,), _ = one('s2', [z_hat], t)
        q_enc, q_dec, scales0, means0 = D.separate_prior(params)
        common = D.conv1x1(params, ysp_w, ysp_b)
        y_shape = (1, yc, yh, yw)
        masks = D.get_mask_four_parts(*y_shape)
        y_hat_so_far = np.zeros(y_shape, dtype=np.float32)
        t['ad'] = 0.0
        for k, (mask, stream) in enumerate(zip(masks, y_streams)):
            if k == 0:
                s_, m_ = scales0, means0
            else:
                (s_, m_), _ = one('s3p%d' % k, [y_hat_so_far, common], t)
            cs = np.maximum(D.compact_masked(s_, mask), np.float32(D.SCALE_MIN)).astype(np.float32)
            cm = D.compact_masked(m_, mask).astype(np.float32)
            t0 = time.time()
            vals = decode_stream(stream, cs, cm)
            t['ad'] += time.time() - t0
            y_hat_so_far = y_hat_so_far + D.scatter_masked(vals, mask, y_shape)
        y_hat = (y_hat_so_far * q_dec).astype(np.float32)
    x_hat = None
    if not args.no_s4:
        (x_hat,), _ = one('s4', [y_hat], t)

    t['png'] = 0.0
    if args.out and x_hat is not None:
        from PIL import Image
        t0 = time.time()
        img = np.clip((x_hat[0].transpose(1, 2, 0) + 1) * 127.5, 0, 255).astype(np.uint8)
        Image.fromarray(img).save(args.out)
        t['png'] = time.time() - t0
    t['total'] = time.time() - T0
    return t, x_hat, y_hat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('glc')
    ap.add_argument('--out', default='')
    ap.add_argument('--repeat', type=int, default=1)
    ap.add_argument('--no-s4', action='store_true')
    a = ap.parse_args()

    print('=' * 88)
    print('  顺序单 session 解码驱动  AD 后端 = %s' % ad_backend())
    print('=' * 88)
    consts = (np.load(os.path.join(CONSTS, 'z_codebook.npy')),
              np.load(os.path.join(CONSTS, 'ysp_reduce_w.npy')).reshape(256, 768),
              np.load(os.path.join(CONSTS, 'ysp_reduce_b.npy')))

    for rep in range(a.repeat):
        STAGE.clear()
        t, x_hat, _ = decode_one(a.glc, consts, a)
        brk = '  '.join('%s %.2f' % (k, t[k]) for k in
                        ('small', 's2', 's3p1', 's3p2', 's3p3', 's4', 'ad', 'png')
                        if k in t)
        print('第%d轮  %s\n   ⇒ 总 %.2f s%s'
              % (rep + 1, brk, t['total'], ('   输出 ' + a.out) if a.out else ''), flush=True)
    print('DEC_SEQ_DONE')


if __name__ == '__main__':
    main()
