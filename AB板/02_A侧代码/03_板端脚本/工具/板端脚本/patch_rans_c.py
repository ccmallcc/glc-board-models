#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""patch_rans_c.py —— 把 C 版 rANS 接进 rans_ad_np.py（A 侧 2026-10-12）

做法（最小侵入、可回退）：
  ① 备份 rans_ad_np.py -> rans_ad_np.py.bak_py
  ② 在文件里插入 C 库加载器（ctypes 加载同目录的 rans_fast.so）
  ③ 原 `decode_symbols` 改名 `_decode_symbols_py`（纯 Python 实现原样保留）
  ④ 新增 `decode_symbols` 做分发：有 .so 走 C，否则原样走 Python
  ⇒ `decode_stream` / `decode_stream_symbols` 以及所有 `decode_board_*.py` **无需改动**。

开关：`GLC_AD_BACKEND=python` 可强制走纯 Python（对拍用）。
缺 rans_fast.so 时自动退回 Python，行为与打补丁前完全一致。
"""
import os
import shutil
import sys

P = sys.argv[1] if len(sys.argv) > 1 else '/root/tp5603_drv/glcdec/rans_ad_np.py'
src = open(P, encoding='utf-8').read()
if 'rans_fast.so' in src:
    print('已经打过补丁，跳过：' + P)
    raise SystemExit(0)
shutil.copy(P, P + '.bak_py')
print('已备份 -> ' + P + '.bak_py')

LOADER = '''

# ---------------------------------------------------------------- C 加速（A 侧 2026-10-12）
# 本文件的逐符号 Python 循环实测 **3.497 s / 65536 符号**（约 53 us/符号），瓶颈是
# `int(row[s+1])` 这类 numpy 标量索引（每次都要 numpy->Python 转换）+ 线性扫描。
# rans_fast.c 把同一段循环原样搬到 C（逐位对齐本文件的 _decode_symbols_py）：
# 实测 **0.063 s（55x）**，4 个相位对拍全部 bit-identical。
# 缺 .so 时自动退回纯 Python；GLC_AD_BACKEND=python 可强制走纯 Python。
import ctypes as _ctypes

_RANS_FAST = None
_RANS_FAST_ERR = ''
if os.environ.get('GLC_AD_BACKEND', 'c').lower() not in ('python', 'py', '0', 'off'):
    _so = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rans_fast.so')
    if os.path.exists(_so):
        try:
            _lib = _ctypes.CDLL(_so)
            _i32p = _ctypes.POINTER(_ctypes.c_int32)
            _lib.rans_decode.argtypes = [_ctypes.POINTER(_ctypes.c_uint8), _ctypes.c_long,
                                         _i32p, _ctypes.c_long, _i32p, _ctypes.c_long,
                                         _i32p, _i32p, _i32p]
            _lib.rans_decode.restype = _ctypes.c_int
            _RANS_FAST = _lib
        except OSError as _e:
            _RANS_FAST_ERR = str(_e)
    else:
        _RANS_FAST_ERR = '缺 ' + _so


def ad_backend():
    """当前 AD 后端：'c'（有 rans_fast.so）或 'python'。"""
    return 'c' if _RANS_FAST is not None else 'python'


def _decode_symbols_c(payload, indexes, cdf, cdf_len, offset):
    idx = np.ascontiguousarray(np.asarray(indexes).reshape(-1), dtype=np.int32)
    n = idx.size
    out = np.empty(n, dtype=np.int32)
    if n == 0:
        return out
    buf = (_ctypes.c_uint8 * len(payload)).from_buffer_copy(bytes(payload))
    cdf = np.ascontiguousarray(cdf, dtype=np.int32)
    cdf_len = np.ascontiguousarray(cdf_len, dtype=np.int32)
    offset = np.ascontiguousarray(offset, dtype=np.int32)
    i32p = _ctypes.POINTER(_ctypes.c_int32)
    rc = _RANS_FAST.rans_decode(buf, _ctypes.c_long(len(payload)),
                                idx.ctypes.data_as(i32p), _ctypes.c_long(n),
                                cdf.ctypes.data_as(i32p), _ctypes.c_long(cdf.shape[1]),
                                cdf_len.ctypes.data_as(i32p),
                                offset.ctypes.data_as(i32p),
                                out.ctypes.data_as(i32p))
    if rc != 0:
        raise ValueError('rans_decode rc=%d（码流可能损坏）' % rc)
    return out

'''

anchor = '# ---------------------------------------------------------------- rANS 解码'
assert anchor in src, '找不到锚点：rANS 解码 分节'
src = src.replace(anchor, LOADER + '\n' + anchor, 1)

old = 'def decode_symbols(payload: bytes, indexes: np.ndarray,'
assert old in src, '找不到 decode_symbols 定义'
src = src.replace(old, 'def _decode_symbols_py(payload: bytes, indexes: np.ndarray,', 1)

marker = 'def decode_stream_symbols(payload: bytes, scales: np.ndarray) -> np.ndarray:'
assert marker in src, '找不到 decode_stream_symbols 定义'
DISPATCH = '''def decode_symbols(payload: bytes, indexes: np.ndarray,
                   cdf: np.ndarray, cdf_len: np.ndarray, offset: np.ndarray) -> np.ndarray:
    """按 rans64 格式解出 symbol 序列（int32）。有 rans_fast.so 时走 C（逐位等价）。"""
    if _RANS_FAST is not None:
        return _decode_symbols_c(payload, indexes, cdf, cdf_len, offset)
    return _decode_symbols_py(payload, indexes, cdf, cdf_len, offset)


'''
src = src.replace(marker, DISPATCH + marker, 1)
open(P, 'w', encoding='utf-8').write(src)
print('patched OK: ' + P)
