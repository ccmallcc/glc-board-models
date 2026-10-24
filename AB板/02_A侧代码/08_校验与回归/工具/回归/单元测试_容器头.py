#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单元测试_容器头.py —— 验 256/512 两种尺寸下的容器头、z 段、尺寸推导、以及 512 的守卫

为什么要有它
------------
2026-10-18 把 `glc_board_full.py` 的尺寸参数化了（`GLC_SIZE`），512 的容器/PL 路径
第一次有了统一来源。但 512 **没上过板**，所以这里只做**纯算术/字节级**验证：

  T1  256 的头，逐字节等于"独立按字面量拼出来的历史布局"（**回归证明：产线路径没变**）
  T2  256 的推导值 = 历史常量 (L=16, Z=4, NSYM=16384, zpay=28, OUT_MAX=65536, CHUNK=512KB)
  T3  512 的推导值 = (L=32, Z=8, NSYM=65536, zpay=112, OUT_MAX=262144, CHUNK=576KB)
  T4  512 的头 76 B，10 个 u32 = (512,512,512,512,256,32,32,256,8,8)，z_count=64，z 段 112
  T5  z 段定长打包：16 个 14 bit 索引 = 28 B；64 个 = 112 B；且首字节/末字节对齐正确
  T6  守卫：只设 GLC_SIZE=512 而不给 GLC_ALLOW_512=1 时，**必须拒绝导入**

用法：python3 单元测试_容器头.py
退出码：0 全过 / 1 有失败
"""
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MODDIR = os.path.abspath(os.path.join(HERE, '..', '板端程序'))
FAILS = []

PROBE = r'''
import sys, struct, json
sys.path.insert(0, %r)
import glc_board_full as G
h = G.build_header(%d, %d, [64, 60, 52, 48])
print(json.dumps({
  "L": G.L, "Z": G.Z, "NSYM": G.NSYM, "zpay": G.Z_PAY_BYTES,
  "outmax": G.OUT_MAX_BYTES, "chunk": G.CHUNK_BYTES,
  "hlen": len(h), "hex": h.hex(),
  "hdr10": list(struct.unpack(">10I", h[8:48])),
  "zcount": struct.unpack(">I", h[48:52])[0],
  "zlen": struct.unpack(">I", h[52:56])[0],
}))
'''


def run(size, allow, zcount, zpay):
    env = dict(os.environ)
    env['GLC_SIZE'] = str(size)
    env['PYTHONIOENCODING'] = 'utf-8'
    if allow:
        env['GLC_ALLOW_512'] = '1'
    else:
        env.pop('GLC_ALLOW_512', None)
    code = PROBE % (MODDIR, zcount, zpay)
    r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', env=env)
    return r


def check(name, cond, detail=''):
    print(('  ✅ ' if cond else '  ❌ ') + name + (('   ' + detail) if detail else ''))
    if not cond:
        FAILS.append(name)


def main():
    print('模块目录: %s' % MODDIR)

    # ---------------- 256：回归证明 ----------------
    r = run(256, True, 16, 28)
    check('256 能导入', r.returncode == 0, (r.stderr or '').strip()[-80:])
    import json
    d = json.loads(r.stdout.strip().splitlines()[-1])

    check('T2 256 推导值 = 历史常量',
          (d['L'], d['Z'], d['NSYM'], d['zpay'], d['outmax'], d['chunk']) == (16, 4, 16384, 28, 65536, 524288),
          'L=%d Z=%d NSYM=%d zpay=%d OUT_MAX=%d CHUNK=%d' %
          (d['L'], d['Z'], d['NSYM'], d['zpay'], d['outmax'], d['chunk']))

    # 独立按字面量拼一份"历史布局"，逐字节比对
    ref = struct.pack(">4sBBH", b"GLC2", 2, 0, 0)
    for v in (256, 256, 256, 256, 256, 16, 16, 256, 4, 4):
        ref += struct.pack(">I", v)
    ref += struct.pack(">I", 16) + struct.pack(">I", 28)
    for v in (64, 60, 52, 48):
        ref += struct.pack(">I", v)
    ref += struct.pack(">I", 0)
    check('T1 256 头逐字节 = 历史布局', ref.hex() == d['hex'] and len(ref) == 76,
          '%d B' % len(ref))

    # ---------------- 512 ----------------
    r2 = run(512, True, 64, 112)
    check('512 给了 GLC_ALLOW_512 才允许导入', r2.returncode == 0, (r2.stderr or '').strip()[-80:])
    if r2.returncode == 0:
        e = json.loads(r2.stdout.strip().splitlines()[-1])
        check('T3 512 推导值',
              (e['L'], e['Z'], e['NSYM'], e['zpay'], e['outmax'], e['chunk']) == (32, 8, 65536, 112, 262144, 589824),
              'L=%d Z=%d NSYM=%d zpay=%d OUT_MAX=%d CHUNK=%d' %
              (e['L'], e['Z'], e['NSYM'], e['zpay'], e['outmax'], e['chunk']))
        check('T4 512 头 76 B 且字段正确',
              e['hlen'] == 76 and e['hdr10'] == [512, 512, 512, 512, 256, 32, 32, 256, 8, 8]
              and e['zcount'] == 64 and e['zlen'] == 112,
              'hdr10=%s' % (e['hdr10'],))

    # ---------------- T5：z 段定长打包（独立实现，不依赖模块） ----------------
    def pack_bits(vals, bits):
        acc = nb = 0
        out = bytearray()
        for v in vals:
            acc = (acc << bits) | v
            nb += bits
            while nb >= 8:
                nb -= 8
                out.append((acc >> nb) & 0xFF)
                acc &= (1 << nb) - 1 if nb else 0
        if nb:
            out.append((acc << (8 - nb)) & 0xFF)
        return bytes(out)

    z16 = pack_bits(list(range(16)), 14)
    seq = [(i * 251 + 16000) % 16384 for i in range(64)]   # idx0=16000：首字节应非零，才检验得出 MSB 优先
    z64 = pack_bits(seq, 14)
    check('T5 16 个 14bit 索引 = 28 B', len(z16) == 28, '%d B' % len(z16))
    check('T5b 64 个 14bit 索引 = 112 B', len(z64) == 112, '%d B' % len(z64))
    # 首字节 = 第一个索引的**高 8 位**（MSB 优先）
    idx0 = seq[0]
    check('T5c MSB 优先（首字节 = idx0 >> 6）', z64[0] == ((idx0 >> 6) & 0xFF),
          'idx0=%d 首字节=0x%02X 期望 0x%02X' % (idx0, z64[0], (idx0 >> 6) & 0xFF))

    # ---------------- T6：守卫 ----------------
    r3 = run(512, False, 64, 112)
    check('T6 512 不给开关必须拒绝', r3.returncode != 0 and 'GLC_ALLOW_512' in (r3.stderr or ''),
          'rc=%d' % r3.returncode)
    r4 = run(384, True, 16, 28)
    check('T6b 非法尺寸必须拒绝', r4.returncode != 0, 'rc=%d' % r4.returncode)

    print('\n' + '=' * 62)
    if FAILS:
        print('失败 %d 条：%s' % (len(FAILS), ' / '.join(FAILS)))
        return 1
    print('全部通过 ✅  256 路径逐字节未变；512 的尺寸/头/z 段推导自洽（**未上板**）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
