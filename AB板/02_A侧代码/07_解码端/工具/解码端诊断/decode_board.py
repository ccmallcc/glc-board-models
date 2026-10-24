#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""板端 GLC 解码（不用 PC）：

  容器(.glc) → z 索引解包 + 码本 → z_hat
             → S2 子图(NPU) → params(1,768,16,16)
             → separate_prior + 1x1 conv(ysp_reduce)
             → 4 个相位：S3p1/2/3(NPU) 给 scales/means + rANS AD 解 y
             → y_hat = y_hat_so_far * q_dec
             → S4 子图(NPU, int8 版) → x_hat → PNG

依赖：numpy、同目录的 `rans_ad_np.py`（纯 Python rANS AD）、板上的 icraft-run 与
      /root/glc/models/{s2,s3_phase1..3,s4_int8} 子图。

用法：
  python3 decode_board.py <container.glc> [--out out.png] [--npz out.npz] [--no-s4]
"""
import argparse
import os
import shutil
import struct
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ICRAFT = os.environ.get('GLC_ICRAFT', '/usr/bin/icraft-run')
MODELS = os.environ.get('GLC_MODELS', '/root/glc/models')
CONSTS = os.environ.get('GLC_CONSTS', '/root/glc/consts')
SCRATCH = os.environ.get('GLC_SCRATCH', '/root/tp5603_drv/decode_run')
BACKENDS = os.environ.get('GLC_BACKENDS', 'ZG330,axi://zg330aiu;Host')

SCALE_MIN = 0.11
SCALE_MAX = 256.0
SCALE_LEVELS = 64
Z_INDEX_BITS = 14
HEADER = struct.Struct('>4sBBH17I')
MAGIC = b'GLC2'
VERSION = 2

# key -> (模型目录/名前缀, 输出 NHWC 形状, dump v_id)
SUB = {
    's2':   (os.path.join(MODELS, 's2_hyperdec_fusion_ZG'), [(1, 16, 16, 768)], [184]),
    's3p1': (os.path.join(MODELS, 's3_phase1_ZG'), [(1, 16, 16, 256)] * 2, [178, 182]),
    's3p2': (os.path.join(MODELS, 's3_phase2_ZG'), [(1, 16, 16, 256)] * 2, [178, 182]),
    's3p3': (os.path.join(MODELS, 's3_phase3_ZG'), [(1, 16, 16, 256)] * 2, [178, 182]),
    's4':   (os.path.join(MODELS, os.environ.get('GLC_S4_DIR', 's4_int8'), 's4_gs_generator_ZG'), [(1, 256, 256, 3)], [4107]),
}


# ---------------------------------------------------------------- 容器解析
def unpack_fixed_width(payload, count, bit_width):
    values = []
    acc = 0
    bits = 0
    for byte in payload:
        acc = (acc << 8) | byte
        bits += 8
        while bits >= bit_width and len(values) < count:
            bits -= bit_width
            values.append((acc >> bits) & ((1 << bit_width) - 1))
            acc &= (1 << bits) - 1 if bits else 0
    if len(values) != count:
        raise ValueError('定长段被截断: 期望 %d 实得 %d' % (count, len(values)))
    return values


def parse_bitstream(blob):
    """严格照队里 test_image_complement2.py 的语义：21 个字段，长度写在头部。"""
    if len(blob) < HEADER.size:
        raise ValueError('截断的 GLC 头')
    f = HEADER.unpack_from(blob, 0)
    if f[0] != MAGIC or f[1] != VERSION:
        raise ValueError('不是 GLC2 容器: %r v%s' % (f[0], f[1]))
    q_index = f[2]
    if f[3] != 0 or f[20] != 0:
        raise ValueError('不支持的 GLC 标志位')
    dims = f[4:15]            # 11 个维度字段
    lengths = f[15:20]        # z 段 + 4 个相位段的长度
    cursor = HEADER.size
    streams = []
    for ln in lengths:
        streams.append(blob[cursor:cursor + ln])
        cursor += ln
    if cursor != len(blob):
        raise ValueError('容器尾部有多余数据')
    return q_index, dims, streams


# ---------------------------------------------------------------- 四相位掩码
def get_one_channel_four_parts_mask(h, w):
    out = []
    for i, j in ((0, 0), (0, 1), (1, 0), (1, 1)):
        micro = np.zeros((2, 2), dtype=bool)
        micro[i, j] = True
        m = np.tile(micro, ((h + 1) // 2, (w + 1) // 2))[:h, :w]
        out.append(m.reshape(1, 1, h, w))
    return out


def get_mask_four_parts(batch, channel, height, width):
    assert channel % 4 == 0
    m = np.ones((batch, channel // 4, height, width), dtype=bool)
    m0, m1, m2, m3 = get_one_channel_four_parts_mask(height, width)
    return [np.concatenate(parts, axis=1) for parts in (
        (m * m0, m * m1, m * m2, m * m3),
        (m * m3, m * m2, m * m1, m * m0),
        (m * m2, m * m3, m * m0, m * m1),
        (m * m1, m * m0, m * m3, m * m2))]


def compact_masked(t, mask_bool):
    return t[np.broadcast_to(mask_bool, t.shape)]


def scatter_masked(compact, mask_bool, shape):
    out = np.zeros(shape, dtype=np.float32)
    out[np.broadcast_to(mask_bool, shape)] = compact.reshape(-1)
    return out


# ---------------------------------------------------------------- 胶水
def separate_prior(params):
    quant_step, scales, means = np.split(params, 3, axis=1)
    qs = np.maximum(quant_step, np.float32(0.5))
    return (np.float32(1.0) / qs).astype(np.float32), qs.astype(np.float32), scales, means


def conv1x1(params, w, b):
    return (w.astype(np.float64) @ params.reshape(768, -1).astype(np.float64)
            + b.astype(np.float64)[:, None]).astype(np.float32).reshape(1, 256, 16, 16)


def to_nhwc(a):
    return np.ascontiguousarray(a.transpose(0, 2, 3, 1))


def to_nchw(a):
    return np.ascontiguousarray(a.transpose(0, 3, 1, 2))


# ---------------------------------------------------------------- v_id 自动取值
def json_output_vids(base):
    """★ 从 _ZG.json 里取 `Output` 节点的 `inputs` —— **这才是 --dump_ftmp 该用的 v_id**。

    为什么需要它：不同机器/不同标定编出来的模型，**输出 v_id 会不一样**。
    实测（2026-10-10）：s4_int8 的正确输出 v_id 是 **4107**，而表里长期写的 `4115`
    **在该模型里根本不存在** ⇒ `--dump_ftmp 4115` 会**静默不 dump**，报"s4 没产出 v_id=4115"。
    用编码侧 5 个子图交叉校准过：s1 -> [3310,3314]、s2 -> [184]、s3p1~3 -> [178,182]，
    与板端实测能 dump 出来的完全一致 ⇒ 这条规则可靠。
    """
    import json
    d = json.load(open(base + '.json', encoding='utf-8'))
    for o in d['ops']:
        if str(o.get('_type_key', '')).endswith('::Output'):
            return [v for v in (o.get('inputs') or []) if isinstance(v, int)]
    return []


def resolve_vids(base, vids, tag):
    """表里的 v_id 若与模型实际输出不符，就以模型为准并告警。"""
    try:
        real = json_output_vids(base)
    except Exception as e:
        print('    [v_id] 读 json 失败(%s)，沿用表里的 %s' % (e, vids), flush=True)
        return vids
    if real and list(real) != list(vids):
        print('    [v_id] ⚠️ %s 表里写 %s，模型实际输出是 %s —— **以模型为准**'
              % (tag, vids, real), flush=True)
        return real
    return vids

# ---------------------------------------------------------------- NPU 子图
def npu(key, inputs):
    base, shapes, vids = SUB[key]
    vids = resolve_vids(base, vids, key)
    for p in (base + '.json', base + '.raw'):
        if not os.path.exists(p):
            raise SystemExit('缺子图: ' + p)
    run = os.path.join(SCRATCH, 'run_' + key)
    shutil.rmtree(run, ignore_errors=True)
    os.makedirs(run)
    ins = []
    for i, t in enumerate(inputs):
        fp = os.path.join(run, 'in%d.ftmp' % i)
        to_nhwc(np.ascontiguousarray(t, dtype=np.float32)).tofile(fp)
        ins.append(fp)
    argv = [ICRAFT, '--json', base + '.json', '--raw', base + '.raw',
            '--input', ';'.join(ins), '--backends', BACKENDS,
            '--log_path', os.path.join(run, 'log'),
            '--dump_format', 'SFB', '--dump_ftmp', ','.join(str(v) for v in vids)]
    argv += os.environ.get('GLC_RUN_EXTRA', '').split()
    t0 = time.time()
    p = subprocess.run(argv, cwd=run, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    dt = time.time() - t0
    outs = []
    for v, shp in zip(vids, shapes):
        fp = os.path.join(run, 'log', os.path.basename(base).replace('_ZG', ''), 'ftmpSFB', '%d.ftmp' % v)
        if not os.path.exists(fp):
            tail = p.stdout.decode('utf-8', 'replace')[-1500:]
            raise SystemExit('%s 没产出 v_id=%d\n%s' % (key, v, tail))
        outs.append(to_nchw(np.fromfile(fp, dtype=np.float32).reshape(shp)))
    print('    [NPU] %-5s %5.1fs' % (key, dt), flush=True)
    return outs


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('glc')
    ap.add_argument('--out', default='')
    ap.add_argument('--npz', default='')
    ap.add_argument('--no-s4', action='store_true', help='只跑到 y_hat（不跑 S4）')
    a = ap.parse_args()

    sys.path.insert(0, HERE)
    from rans_ad_np import decode_stream

    blob = open(a.glc, 'rb').read()
    t_all = time.time()
    q_index, dims, streams = parse_bitstream(blob)
    (oh, ow, ph, pw, yc, yh, yw, zc, zh, zw, zcnt) = dims
    z_payload, y_streams = streams[0], streams[1:]
    print('  容器 %s: q=%d 尺寸=%dx%d latent=%dx%dx%d z=%dx%dx%d streams=%d'
          % (os.path.basename(a.glc), q_index, oh, ow, yc, yh, yw, zc, zh, zw, len(streams)))

    codebook = np.load(os.path.join(CONSTS, 'z_codebook.npy'))
    ysp_w = np.load(os.path.join(CONSTS, 'ysp_reduce_w.npy')).reshape(256, 768)
    ysp_b = np.load(os.path.join(CONSTS, 'ysp_reduce_b.npy'))

    z_idx = np.asarray(unpack_fixed_width(z_payload, zcnt, Z_INDEX_BITS), dtype=np.int64)
    z_hat = codebook[z_idx].reshape(1, zh, zw, zc).transpose(0, 3, 1, 2)
    z_hat = np.ascontiguousarray(z_hat).astype(np.float32)

    (params,) = npu('s2', [z_hat])
    q_enc, q_dec, scales0, means0 = separate_prior(params)
    common = conv1x1(params, ysp_w, ysp_b)

    y_shape = (1, yc, yh, yw)
    masks = get_mask_four_parts(*y_shape)
    y_hat_so_far = np.zeros(y_shape, dtype=np.float32)
    t_ent = 0.0
    for k, (mask, stream) in enumerate(zip(masks, y_streams)):
        if k == 0:
            s_, m_ = scales0, means0
        else:
            s_, m_ = npu('s3p%d' % k, [y_hat_so_far, common])
        cs = np.maximum(compact_masked(s_, mask), np.float32(SCALE_MIN)).astype(np.float32)
        cm = compact_masked(m_, mask).astype(np.float32)
        t0 = time.time()
        vals = decode_stream(stream, cs, cm)
        t_ent += time.time() - t0
        print('    相位%d: %d 个符号, %d B 流, AD %.1f ms'
              % (k, len(vals), len(stream), (time.time() - t0) * 1e3), flush=True)
        y_hat_so_far = y_hat_so_far + scatter_masked(vals, mask, y_shape)

    y_hat = (y_hat_so_far * q_dec).astype(np.float32)
    print('  熵解码合计 %.1f ms' % (t_ent * 1e3))

    x_hat = None
    if not a.no_s4:
        (x_hat,) = npu('s4', [y_hat])
    if a.npz:
        np.savez(a.npz, y_hat=y_hat, x_hat=x_hat if x_hat is not None else np.zeros(1))
        print('  已存 npz: ' + a.npz)
    if a.out and x_hat is not None:
        from PIL import Image
        img = np.clip((x_hat[0].transpose(1, 2, 0) + 1) * 127.5, 0, 255).astype(np.uint8)
        Image.fromarray(img).save(a.out)
        print('  已存 PNG: %s' % a.out)
    print('  总耗时 %.1f s' % (time.time() - t_all))


if __name__ == '__main__':
    main()
