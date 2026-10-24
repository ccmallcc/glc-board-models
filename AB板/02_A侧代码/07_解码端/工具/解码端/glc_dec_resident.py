#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""glc_dec_resident.py —— B 板「常驻解码引擎」（A 侧 2026-10-12）

为什么要有它
------------
解码端原来的做法是 `decode_board_bf16.py`：**每张图**为每个子图 fork 一次
`icraft-run`。实测一张 256x256 容器 **70.5 s**，分解：

    s2    1.4 s
    s3p1  1.1 s
    s3p2  1.1 s
    s3p3  1.1 s
    s4   60.9 s      <-- 其中 21.3 s 只是"读 452 MB raw"（21.2 MB/s）
    AD 熵解码 3.497 s
    ---------------------------------
    合计 ~70.5 s

而 452 MB 的读盘 + json 解析 + 建网 + apply()，**每张图都要重做一遍**，纯属浪费。
本脚本把这些只做一次，之后每张容器只做 forward：

    [载入阶段，一次]  常量 + 5 个子图（含 lazyLoadParamsFromFile + apply）
    [每张容器]        s2 fwd -> 胶水 -> 3x(s3 fwd + AD) -> s4 fwd -> PNG

接口与 decode_board_bf16.py **逐位等价**：容器解析 / 四相位掩码 / 1x1 conv /
separate_prior 全部直接 import 自 `decode_board_bf16`（同一目录），避免两份实现漂移。
唯一新增的是 `--fast-ad`：用 C 扩展 `rans_fast.so` 替代纯 Python 的 rANS 逐符号循环
（板上实测那一段 3.497 s；C 版逐位等价，见 rans_fast.c 头注释）。

用法
----
    python3 glc_dec_resident.py img1.glc [img2.glc ...] [选项]

选项
----
    --out-dir DIR     PNG 输出目录（默认 /root/glc/dec_out）
    --warm            载入前用 read() 把模型文件读一遍预热页缓存
    --fast-ad         用 C 扩展做 rANS（默认开，除非给了 --slow-ad）
    --slow-ad         强制用纯 Python rANS（用于对拍）
    --check-ad        每相位两种实现都跑，比对是否逐位一致
    --npz-dir DIR     额外把每张图的 y_hat/x_hat 存 npz（对拍用）
    --no-s4           只跑到 y_hat
    --repeat N        每个容器重复跑 N 次（第 2 次起的耗时才是稳态值）
    --load-only       只载入不跑图（测载入时间）

⚠️ 只读模型；只在 --out-dir / --npz-dir 下写文件。
"""
import argparse
import ctypes
import json
import os
import struct
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
GLC_DIR = os.environ.get('GLC_LIB_DIR', '/root/glc')
sys.path.insert(0, GLC_DIR)
sys.path.insert(0, HERE)

# 复用 B 板既有的、已实测跑通的实现（容器解析 / 掩码 / 胶水 / 子图表）
import decode_board_bf16 as D          # noqa: E402
from rans_ad_np import build_indexes, quantized_cdf_table   # noqa: E402

from icraft import xir, xrt            # noqa: E402
from icraft import host_backend        # noqa: E402
from icraft.zg330backend import ZG330Backend, OcmOpt         # noqa: E402

MODELS = os.environ.get('GLC_MODELS', '/root/glc/models')
CONSTS = os.environ.get('GLC_CONSTS', '/root/glc/consts')
DEV_URL = os.environ.get('GLC_DEV_URL', 'axi://zg330aiu?npu=0x40000000&dma=0x80000000')
SO = os.path.join(HERE, 'rans_fast.so')

# ★★ 载入顺序至关重要（2026-10-12 实测，diag_matrix.py 矩阵）：
#   s4 的网络逻辑地址空间跨 3.43 GB（ICRAFT 报 "Network size:3431640960 beyond 2GB"），
#   远超 PL DDR 的 2 GB 窗口，靠 ETM 优化才能在单独运行时落进物理内存。
#   它**必须第一个 apply()**，否则后载入的 s2/s3 会把它挤坏；反过来 s4 先占位后，
#   s2/s3p1/s3p2/s3p3 再载入也能全部正确（实测三者输出与单独运行逐位相同）。
#   矩阵实测：
#     [s2,s3p1]              -> 两者皆 ✓（多 session 共存本身没问题）
#     [s2,s4]                -> s4 ✗
#     [s2,s3p1,s4]           -> s3p1 ✗, s4 ✗
#     [s4,s2,s3p1]           -> s4 ✓ 但 s2 ✗ s3p1 ✗
#     [s4,s2,s3p1,s3p2,s3p3] -> **全 ✓**（当前采用）
#   另：userReuseSegment 手工钉内存那条路**已验证有害**（钉了 s3p1 反而错），默认关闭。
ORDER = ['s4', 's2', 's3p1', 's3p2', 's3p3']

# GLC_USER_SEGMENT=1 时给每个网络单独划的 PL DDR 大小（MB）。
# ⚠️ 实测结论：这条路是**否定结果** —— 钉住 WEIGHT/INSTR/INPUT/OUTPUT 之后
#    s3p1 输出反而不对（FTMP 段大小与清单对不上，icraft 内部池 ≠ 它报告的值）。
#    保留代码仅供复现，默认不要开。
SEG_MB = {'s2': 32, 's3p1': 24, 's3p2': 24, 's3p3': 24, 's4': 768}
_CHUNKS = []


# ================================================================ rANS C 加速
class FastAD(object):
    """把 rans_ad_np.decode_symbols 的逐符号循环换到 C（逐位等价）。"""

    def __init__(self, so_path=SO):
        self.ok = False
        self.err = ''
        if not os.path.exists(so_path):
            self.err = '缺 %s（先 bash build_rans_fast.sh）' % so_path
            return
        try:
            self.lib = ctypes.CDLL(so_path)
        except OSError as e:
            self.err = 'dlopen 失败: %s' % e
            return
        i32p = ctypes.POINTER(ctypes.c_int32)
        self.lib.rans_decode.argtypes = [
            ctypes.POINTER(ctypes.c_uint8), ctypes.c_long,
            i32p, ctypes.c_long,
            i32p, ctypes.c_long,
            i32p, i32p, i32p]
        self.lib.rans_decode.restype = ctypes.c_int
        self.lib.rans_fast_version.restype = ctypes.c_char_p
        self.ver = self.lib.rans_fast_version().decode()
        self.ok = True

    def symbols(self, payload, indexes, cdf, cdf_len, offset):
        idx = np.ascontiguousarray(indexes.reshape(-1), dtype=np.int32)
        n = idx.size
        out = np.empty(n, dtype=np.int32)
        if n == 0:
            return out
        buf = (ctypes.c_uint8 * len(payload)).from_buffer_copy(payload)
        i32p = ctypes.POINTER(ctypes.c_int32)
        rc = self.lib.rans_decode(
            buf, ctypes.c_long(len(payload)),
            idx.ctypes.data_as(i32p), ctypes.c_long(n),
            cdf.ctypes.data_as(i32p), ctypes.c_long(cdf.shape[1]),
            cdf_len.ctypes.data_as(i32p),
            offset.ctypes.data_as(i32p),
            out.ctypes.data_as(i32p))
        if rc != 0:
            raise RuntimeError('rans_decode rc=%d（码流可能损坏）' % rc)
        return out


SMALL_VIA_RUN = bool(os.environ.get('GLC_SMALL_VIA_RUN'))
_FAST = None


def fast_ad():
    global _FAST
    if _FAST is None:
        _FAST = FastAD()
    return _FAST


def ad_decode(payload, scales, means, use_fast):
    """返回 (y_float32, 耗时秒)。use_fast=False 走纯 Python 版。"""
    sc = np.asarray(scales)
    shape = sc.shape
    t0 = time.time()
    idx = build_indexes(sc.reshape(-1))
    if use_fast:
        cdf, cdf_len, offset = quantized_cdf_table()
        cdf = np.ascontiguousarray(cdf, dtype=np.int32)
        cdf_len = np.ascontiguousarray(cdf_len, dtype=np.int32)
        offset = np.ascontiguousarray(offset, dtype=np.int32)
        sym = fast_ad().symbols(payload, idx, cdf, cdf_len, offset)
    else:
        from rans_ad_np import decode_symbols
        cdf, cdf_len, offset = quantized_cdf_table()
        sym = decode_symbols(payload, idx, cdf, cdf_len, offset)
    y = sym.astype(np.float32)
    if means is not None:
        y = y + np.asarray(means, dtype=np.float32).reshape(-1)
    return y.reshape(shape), time.time() - t0


# ================================================================ 常驻子图
class ResNet(object):
    """一个常驻 session：载入一次，之后反复 forward。"""

    def __init__(self, key, base, vids, out_shapes, dev, quiet=False):
        self.key = key
        self.vids = vids
        self.out_shapes = out_shapes
        self.base = base
        self.t = {}
        j, r = base + '.json', base + '.raw'
        for p in (j, r):
            if not os.path.exists(p):
                raise SystemExit('缺子图: ' + p)
        self.raw_mb = os.path.getsize(r) / 1048576.0

        t = time.time()
        self.net = xir.Network.CreateFromJsonFile(j)
        self.t['json'] = time.time() - t

        t = time.time()
        self.net.lazyLoadParamsFromFile(r)
        self.t['lazy'] = time.time() - t

        self.in_names = []
        self.in_shapes = []
        self.in_tt = []
        for ten in self.net.inputs():
            try:
                self.in_names.append(ten.name)
            except Exception:                 # noqa: BLE001
                self.in_names.append(str(ten))
            tt = ten.tensorType()
            self.in_tt.append(tt)
            try:
                self.in_shapes.append(list(tt.getShape()))
            except Exception:                 # noqa: BLE001
                self.in_shapes.append([])

        nv = self.net.view(0).setOutputsOrderByValueIds(list(vids))

        def _mk():
            s = xrt.Session.Create([ZG330Backend, host_backend.HostBackend], nv,
                                   [dev, xrt.HostDevice.Default()])
            b = ZG330Backend(s.backends[0])
            b.ocmOptimize(OcmOpt.OPTION1)
            # ★ GLC_USER_SEGMENT=1 —— 给每个网络单独划 PL DDR 内存块。
            #   不划的话，各 session 的物理地址都从同一基址开始 → 后 apply 的
            #   覆盖先 apply 的（实测：s4_first 时 s3 输出爆到 -3.7e19）。
            #   ZG330Backend.userReuseSegment 文档原文：「用于复用数据或内存空间，
            #   减少多网络部署对 etm 的使用量」，:note 在 apply 前调用。
            if os.environ.get('GLC_USER_SEGMENT'):
                from icraft.zg330backend import SegmentType
                import json as _json
                region = dev.getMemRegion('plddr')
                man = {}
                try:
                    with open(os.environ.get('GLC_SEG_MANIFEST',
                                             '/root/glc/seg_manifest.json')) as _f:
                        man = _json.load(_f).get(key, {})
                except Exception as _e:            # noqa: BLE001
                    print('      [%s] 读尺寸清单失败: %s' % (key, _e))
                got = []
                for nm in ('WEIGHT', 'INSTR', 'FTMP', 'INPUT', 'OUTPUT'):
                    sz = int(man.get(nm, 0))
                    st = getattr(SegmentType, nm, None)
                    if sz <= 0 or st is None:
                        continue
                    try:
                        # 硬校验①：必须 4096 对齐；硬校验②：chunk 大小须与段精确相等
                        c = region.malloc(sz, False, 4096)
                        _CHUNKS.append(c)
                        b.userReuseSegment(c, st)
                        got.append('%s=%.1fMB@0x%x' % (nm, sz / 1048576.0, c.begin.addr()))
                    except Exception as _e:        # noqa: BLE001
                        m = [l for l in str(_e).splitlines() if 'xception info' in l]
                        print('      [%s] userReuseSegment(%s) ✗ %s'
                              % (key, nm, (m[-1].strip()[:110] if m else str(_e)[:110])))
                self._seg = ' '.join(got) if got else 'seg=none'
            s.enableTimeProfile(True)
            return s

        last = None
        for tag, mod in (('默认', None), ('no-ocm', 'noocm'), ('no-etm', 'noetm')):
            try:
                t = time.time()
                if mod is None:
                    self.sess = _mk()
                else:
                    self.sess = xrt.Session.Create(
                        [ZG330Backend, host_backend.HostBackend], nv,
                        [dev, xrt.HostDevice.Default()])
                    b = ZG330Backend(self.sess.backends[0])
                    if mod == 'noetm':
                        b.disableEtmOptimize()
                    else:
                        pass
                    self.sess.enableTimeProfile(True)
                self.t['sess'] = time.time() - t
                t = time.time()
                self.sess.apply()
                self.t['apply'] = time.time() - t
                self.variant = tag
                break
            except Exception as e:            # noqa: BLE001
                last = e
                msg = [l for l in str(e).splitlines() if 'xception info' in l or 'Network' in l]
                if not quiet:
                    print('      [%s/%s] ✗ %s' % (key, tag,
                          (msg[-1].strip()[:120] if msg else str(e)[:120])), flush=True)
                self.sess = None
        if self.sess is None:
            raise SystemExit('%s 载入失败: %s' % (key, last))
        self.total = sum(self.t.values())

    def info(self):
        return ('%-5s raw %6.1f MB  json %5.2f  lazy %6.2f  sess %5.2f  apply %5.2f  = %6.2f s  '
                '[%s]  %s  in=%s %s' % (
                    self.key, self.raw_mb, self.t['json'], self.t['lazy'],
                    self.t['sess'], self.t['apply'], self.total, self.variant,
                    getattr(self, '_seg', '-'), ','.join(self.in_names), self.in_shapes))

    def forward(self, arrays):
        """arrays：按 in_names 顺序，**NCHW** float32。返回按 out_shapes 的 NCHW。

        注意：子图是 NHWC 编译的（与 `icraft-run --input` 的 ftmp 布局一致），
        所以这里必须 to_nhwc 之后再喂，tensorType 的 shape 也要设成 NHWC。
        """
        tens = []
        for tt, a in zip(self.in_tt, arrays):
            nh = D.to_nhwc(np.ascontiguousarray(a, dtype=np.float32))
            tt.setShape(list(nh.shape))
            tens.append(xrt.Tensor(nh, tt))
        outs = self.sess.forward(tens)
        res = []
        for k, (t, shp) in enumerate(zip(outs, self.out_shapes)):
            try:
                import io
                bio = io.BytesIO()
                t.dump(bio, 'SFB')
                arr = np.frombuffer(bio.getvalue(), dtype=np.float32).reshape(shp)
            except Exception as e:            # noqa: BLE001
                raise RuntimeError('%s 输出 %d dump 失败: %s' % (self.key, k, e))
            res.append(D.to_nchw(np.array(arr)))   # NHWC -> NCHW
        return res


def warm_cache(paths):
    """顺序 read() 一遍，把文件拉进页缓存（tmpfs 版会占不可回收内存，页缓存可回收）。"""
    total = 0
    t0 = time.time()
    for p in paths:
        try:
            with open(p, 'rb') as f:
                while True:
                    b = f.read(8 << 20)
                    if not b:
                        break
                    total += len(b)
        except OSError as e:
            print('   预热失败 %s: %s' % (p, e))
    return total / 1048576.0, time.time() - t0


# ================================================================ 单张解码
def decode_one(glc_path, nets, consts, args, tag=''):
    codebook, ysp_w, ysp_b = consts
    blob = open(glc_path, 'rb').read()
    q_index, dims, streams = D.parse_bitstream(blob)
    (oh, ow, ph, pw, yc, yh, yw, zc, zh, zw, zcnt) = dims
    z_payload, y_streams = streams[0], streams[1:]
    t = {}
    T0 = time.time()

    t0 = time.time()
    z_idx = np.asarray(D.unpack_fixed_width(z_payload, zcnt, D.Z_INDEX_BITS), dtype=np.int64)
    z_hat = codebook[z_idx].reshape(1, zh, zw, zc).transpose(0, 3, 1, 2)
    z_hat = np.ascontiguousarray(z_hat).astype(np.float32)
    t['z_decode'] = time.time() - t0

    t0 = time.time()
    if SMALL_VIA_RUN:
        (params,) = D.npu('s2', [z_hat])
    else:
        (params,) = nets['s2'].forward([z_hat])
    t['s2'] = time.time() - t0

    t0 = time.time()
    q_enc, q_dec, scales0, means0 = D.separate_prior(params)
    common = D.conv1x1(params, ysp_w, ysp_b)
    y_shape = (1, yc, yh, yw)
    masks = D.get_mask_four_parts(*y_shape)
    y_hat_so_far = np.zeros(y_shape, dtype=np.float32)
    t['glue'] = time.time() - t0

    t['s3'] = 0.0
    t['ad'] = 0.0
    syms = []
    for k, (mask, stream) in enumerate(zip(masks, y_streams)):
        if k == 0:
            s_, m_ = scales0, means0
        else:
            t0 = time.time()
            if SMALL_VIA_RUN:
                s_, m_ = D.npu('s3p%d' % k, [y_hat_so_far, common])
            else:
                s_, m_ = nets['s3p%d' % k].forward([y_hat_so_far, common])
            t['s3'] += time.time() - t0
        cs = np.maximum(D.compact_masked(s_, mask), np.float32(D.SCALE_MIN)).astype(np.float32)
        cm = D.compact_masked(m_, mask).astype(np.float32)
        yk, dt = ad_decode(stream, cs, cm, args.fast_ad)
        t['ad'] += dt
        if args.check_ad:
            yk2, _ = ad_decode(stream, cs, cm, False)
            same = np.array_equal(yk, yk2)
            print('      相位%d  C/py 逐位一致: %s' % (k, same), flush=True)
            assert same, '相位%d C 版与 Python 版不一致！' % k
        if args.npz_dir and k == 0:
            syms.append(None)
        y_hat_so_far = y_hat_so_far + D.scatter_masked(yk, mask, y_shape)

    t0 = time.time()
    y_hat = (y_hat_so_far * q_dec).astype(np.float32)
    t['yquant'] = time.time() - t0
    # [2026-10-12 诊断] 怀疑 s4 的 forward 会**就地写坏 y_hat**（NPU 把输入缓冲
    #   当暂存区用）。留一份 copy，事后与 base1.npz 对拍即可判定。
    y_hat_pre = y_hat.copy()

    x_hat = None
    t['s4'] = 0.0
    if not args.no_s4:
        t0 = time.time()
        (x_hat,) = nets['s4'].forward([y_hat])
        t['s4'] = time.time() - t0
    t['yhat_corrupt'] = float(np.abs(y_hat - y_hat_pre).max()) if not args.no_s4 else 0.0

    t['png'] = 0.0
    if args.out_dir and x_hat is not None:
        t0 = time.time()
        from PIL import Image
        img = np.clip((x_hat[0].transpose(1, 2, 0) + 1) * 127.5, 0, 255).astype(np.uint8)
        os.makedirs(args.out_dir, exist_ok=True)
        op = os.path.join(args.out_dir, os.path.splitext(os.path.basename(glc_path))[0] + '.png')
        Image.fromarray(img).save(op)
        t['png'] = time.time() - t0
        t['_out'] = op
    if args.npz_dir and x_hat is not None:
        os.makedirs(args.npz_dir, exist_ok=True)
        np.savez(os.path.join(args.npz_dir,
                              os.path.splitext(os.path.basename(glc_path))[0] + '.npz'),
                 y_hat=y_hat, y_hat_pre=y_hat_pre, x_hat=x_hat)
    t['total'] = time.time() - T0
    return t


def fmt_t(t):
    keys = ['z_decode', 's2', 'glue', 's3', 'ad', 'yquant', 's4', 'png']
    return '  '.join('%s %.3f' % (k, t.get(k, 0)) for k in keys)


# ================================================================ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('glc', nargs='*')
    ap.add_argument('--out-dir', default='/root/glc/dec_out')
    ap.add_argument('--npz-dir', default='')
    ap.add_argument('--warm', action='store_true')
    ap.add_argument('--slow-ad', dest='fast_ad', action='store_false')
    ap.add_argument('--fast-ad', dest='fast_ad', action='store_true')
    ap.set_defaults(fast_ad=True)
    ap.add_argument('--check-ad', action='store_true')
    ap.add_argument('--no-s4', action='store_true')
    ap.add_argument('--repeat', type=int, default=1)
    ap.add_argument('--load-only', action='store_true')
    a = ap.parse_args()

    fa = fast_ad()
    print('=' * 92)
    print('  常驻解码引擎  %s' % time.strftime('%Y-%m-%d %H:%M:%S'))
    print('  rANS C 扩展: %s' % (('可用  ' + fa.ver) if fa.ok else ('不可用 -- ' + fa.err)))
    print('  AD 后端: %s' % ('C' if (a.fast_ad and fa.ok) else 'Python'))
    if a.fast_ad and not fa.ok:
        a.fast_ad = False
    print('=' * 92)

    # ---- 常量
    t0 = time.time()
    codebook = np.load(os.path.join(CONSTS, 'z_codebook.npy'))
    ysp_w = np.load(os.path.join(CONSTS, 'ysp_reduce_w.npy')).reshape(256, 768)
    ysp_b = np.load(os.path.join(CONSTS, 'ysp_reduce_b.npy'))
    cdf, cdf_len, offset = quantized_cdf_table()
    t_const = time.time() - t0
    print('[常量] codebook %s  ysp_w %s  熵表 cdf %s  = %.3f s'
          % (codebook.shape, ysp_w.shape, cdf.shape, t_const), flush=True)

    # ---- 页缓存预热
    if a.warm:
        files = []
        for k in order:
            b = D.SUB[k][0]
            files += [b + '.json', b + '.raw']
        mb, dt = warm_cache(files)
        print('[预热] 读入 %.1f MB / %.1f s  (%.1f MB/s)' % (mb, dt, mb / max(dt, 1e-6)), flush=True)

    # ---- 设备 + 子图
    # ★ GLC_SMALL_VIA_RUN=1 —— 「只有 s4 常驻」方案。
    #   动机（2026-10-12 实测）：多 session 同进程**不可靠**（同一份代码连跑三次
    #   结果全不同）；但**每个子图单独一个进程都 100% 逐位正确**。
    #   所以只把 s4（最大的那个）常驻，s2/s3p1..3 每次用 icraft-run 起独立进程
    #   （`decode_board_bf16.npu()`，已被证明与基线逐位相同），
    #   任何时刻每个进程里**只有一个 session**。
    small_via_run = bool(os.environ.get('GLC_SMALL_VIA_RUN'))
    order = ['s4'] if small_via_run else ORDER
    t0 = time.time()
    dev = xrt.Device.Open(DEV_URL)
    print('[设备] Open %.2f s' % (time.time() - t0), flush=True)
    # ★ GLC_DEV_RESET=1[,2] —— 开设备后先 reset。
    #   动机（2026-10-12 实测）：同一份代码同一加载顺序，连跑三次结果全不同
    #   （run1 y_hat 错 / run2 y_hat 对而 x_hat 错 / run3 全对）。怀疑上一个进程
    #   残留的 PL DDR 分配状态影响 s4 的内存规划 —— s4 逻辑地址空间跨 3.43 GB，
    #   必须靠 ETM 优化才能挤进 2 GB，可用内存一变规划就**静默失效**。
    # ★★ 默认 GLC_DEV_RESET=1 —— **必须保留**。
    #   2026-10-12 实测：不做 reset 时，同一份代码同一加载顺序连跑三次结果全不同
    #     run1 y_hat 错(3.62) / run2 y_hat 对而 x_hat 错(40.25) / run3 全对
    #   加上 reset 之后 6/6 全部逐位正确。根因是**上一个进程残留的 PL DDR 分配状态**
    #   污染 s4 的内存规划 —— s4 逻辑地址空间跨 3.43 GB，必须靠 ETM 优化才能挤进
    #   2 GB 的 PL DDR，可用内存一变，规划就**静默失效**（不报错，直接出全白图）。
    #   设 GLC_DEV_RESET=0 可关闭（不推荐）。
    for _lv in [int(x) for x in os.environ.get('GLC_DEV_RESET', '1').split(',')
                if x.strip() and x.strip() != '0']:
        try:
            dev.reset(_lv)
            print('[设备] reset(%d) OK' % _lv, flush=True)
        except Exception as _e:                # noqa: BLE001
            print('[设备] reset(%d) ✗ %s' % (_lv, str(_e)[:120]), flush=True)

    nets = {}
    t_load0 = time.time()
    for k in order:
        base, shapes, vids = D.SUB[k]
        t0 = time.time()
        try:
            n = ResNet(k, base, vids, shapes, dev)
            nets[k] = n
            print('[载入] %s  (%.1f s)' % (n.info(), time.time() - t0), flush=True)
        except SystemExit as e:
            print('[载入] %s ✗ %s   (已耗时 %.1f s)' % (k, e, time.time() - t0), flush=True)
            raise
    t_load = time.time() - t_load0
    print('[就绪] %d 个子图总载入 %.2f s（其中 lazy/读盘 %.2f s）'
          % (len(nets), t_load, sum(n.t['lazy'] for n in nets.values())), flush=True)

    if a.load_only or not a.glc:
        print('LOAD_ONLY_DONE')
        return

    consts = (codebook, ysp_w, ysp_b)
    rows = []
    for rep in range(a.repeat):
        for g in a.glc:
            print('-' * 92)
            print('[容器] %s  第 %d/%d 次' % (os.path.basename(g), rep + 1, a.repeat), flush=True)
            t = decode_one(g, nets, consts, a)
            rows.append(t)
            print('  %s' % fmt_t(t), flush=True)
            print('  ⇒ 总 %.3f s%s' % (t['total'], ('   输出 ' + t['_out']) if '_out' in t else ''),
                  flush=True)

    if len(rows) > 1:
        print('=' * 92)
        avg = {k: float(np.mean([r.get(k, 0) for r in rows])) for k in
               ['z_decode', 's2', 'glue', 's3', 'ad', 'yquant', 's4', 'png', 'total']}
        print('[均值 %d 张] %s' % (len(rows), fmt_t(avg)))
    print('RESIDENT_DEC_DONE')


if __name__ == '__main__':
    main()
