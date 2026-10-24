#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
glc_e2e.py —— 板端**单进程**跑通「操作数 → PL rANS → 真实 GLC2 容器」

与 rans_py.py 的区别（这就是这一步的全部意义）：
    rans_py.py : 只把 4 个 phase 的 payload 打出来，跟 .glc 里已有的 stage 段对拍。
                 —— PL 被**旁路在链路之外**，容器仍然是 A53 CPU 的 glc2_pack 产的。
    glc_e2e.py : PL 出 payload 之后，**自己组 GLC2 容器**
                 （76 B 头 + 28 B z 段 + 4 段 rANS 流），写出一个真 .glc。
                 容器的每一个字节都出自板上这一条链路。

容器格式的权威定义（逐字对齐，不猜）：
    assets/板端代码/glc2_pack.cpp        —— 头 76 B = struct ">4sBBH17I"；z 段 = 16*14/8 = 28 B
    assets/板端代码/glc_board_encoder.h  —— glc_pack_fixed_width（MSB-first 14 bit 定长）

判据：
    1) PL 组出来的容器，必须与 A53 CPU 的 glc2_pack 从**同一份操作数**产出的容器
       **逐字节一致** —— 这才证明 PL 真的顶替了 rANS 核，而不是"另产了一个东西"。
    2) 这个容器必须能被 PC 侧 S4 fp32 解码出图（PSNR 应为 ~21.8 dB）。

用法：
    python3 glc_e2e.py --img img0
    python3 glc_e2e.py --img img0 --ref /root/glc/pack/img0.glc
"""
import argparse
import hashlib
import mmap
import os
import struct
import sys
import time

import numpy as np

REG_BASE = 0x400C0000
REG_LEN = 0x2000

R_START = 0x00
R_RBASE32 = 0x0C
R_RSIZE = 0x10
R_WBASE32 = 0x14
R_NSYM = 0x20
R_DONE = 0x80
R_VER = 0x84
R_STATUS = 0x88
R_PLWORDS = 0x8C
R_NESC = 0x90
R_NBYP = 0x94
R_CYC = 0x98
R_MAXRAW = 0x9C
R_MAXNB = 0xA0
R_NSYM_R = 0xA4
R_TFED = 0xA8

VER_EXPECT = 0x20260922
ADD_VER = 0x20230628

HP_CLK_MHZ = 200.0
Z_INDEX_BITS = 14
HEADER_SIZE = 76
OUT_MAX_BYTES = 16384 * 4

GLC_SCALE_BOUND = np.float32(0.109999999)
GLC_SCALE_TABLE = np.array([
    0.109999999, 0.124404095, 0.14069438, 0.159117803,
    0.179953694, 0.203517973, 0.230167925, 0.26030761,
    0.294393927, 0.332943738, 0.376541555, 0.425848305,
    0.481611609, 0.5446769, 0.616000414, 0.696663439,
    0.787889004, 0.891060233, 1.00774133, 1.13970149,
    1.28894126, 1.4577235, 1.64860713, 1.86448622,
    2.108634, 2.38475204, 2.69702673, 3.05019283,
    3.44960451, 3.90131736, 4.41218138, 4.98994064,
    5.64335394, 6.38233089, 7.2180748, 8.16325474,
    9.23220348, 10.4411287, 11.8083563, 13.3546171,
    15.1033554, 17.0810852, 19.3177948, 21.8473892,
    24.7082233, 27.9436817, 31.6028042, 35.7410774,
    40.4212379, 45.7142525, 51.7003784, 58.4703369,
    66.1268311, 74.7859116, 84.5788345, 95.6541443,
    108.179733, 122.345444, 138.366165, 156.484741,
    176.9758, 200.150177, 226.359055, 256,
], dtype=np.float32)


def build_index(scales):
    """逐位等价于 glc_cdf_table.h 的 glc_build_index（64 行，NaN-safe）。"""
    sc = np.asarray(scales, dtype=np.float32)
    sc = np.where(sc > GLC_SCALE_BOUND, sc, GLC_SCALE_BOUND)
    cnt = (sc[:, None] <= GLC_SCALE_TABLE[None, :63]).sum(axis=1)
    return (63 - cnt).astype(np.uint32)


def pack_fixed_width(values, bit_width):
    """glc_board_encoder.h:184 glc_pack_fixed_width 的逐位等价实现（MSB-first）。"""
    limit = 1 << bit_width
    acc = 0
    nb = 0
    out = bytearray()
    for v in values:
        v = int(v)
        if v < 0 or v >= limit:
            raise ValueError("z index %d 超出 %d bit 范围" % (v, bit_width))
        acc = (acc << bit_width) | v
        nb += bit_width
        while nb >= 8:
            nb -= 8
            out.append((acc >> nb) & 0xFF)
            acc &= (1 << nb) - 1 if nb else 0
    if nb:
        out.append((acc << (8 - nb)) & 0xFF)
    return bytes(out)


def read_hdr(path):
    d = {}
    with open(path, "r") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            p = line.split(" ", 1)
            if len(p) != 2:
                continue
            d[p[0]] = p[1].strip()
    return d


def md5(b):
    return hashlib.md5(b).hexdigest()


class RegWin(object):
    def __init__(self, base=REG_BASE):
        self.fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        self.mm = mmap.mmap(self.fd, REG_LEN, mmap.MAP_SHARED,
                            mmap.PROT_READ | mmap.PROT_WRITE, offset=base)

    def rd(self, off):
        return struct.unpack_from("<I", self.mm, off)[0]

    def wr(self, off, v):
        struct.pack_into("<I", self.mm, off, v & 0xFFFFFFFF)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", default="img0")
    ap.add_argument("--dir", default="")
    ap.add_argument("--ref", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--no_ref", action="store_true")
    args = ap.parse_args()
    if not args.dir:
        args.dir = "/root/glc/pack/%s" % args.img
    if args.no_ref and not args.ref:
        args.ref = "/nonexistent"

    hdr = read_hdr(os.path.join(args.dir, "hdr.txt"))
    img = os.path.basename(args.dir)
    out_path = args.out or ("/root/glc/pack/pl_%s.glc" % img)
    ref_path = args.ref or ("/root/glc/pack/%s.glc" % img)

    import icraft.xrt as xrt
    dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
    mem = dev.defaultMemRegion()
    SIZE = 512 * 1024
    chunk = mem.malloc(SIZE, False, 64)
    rbase = chunk.begin.addr()
    print("== icraft chunk: addr=%d (0x%X) byte_size=%d" % (rbase, rbase, chunk.byte_size))

    reg = RegWin()
    v84 = reg.rd(R_VER)
    vc0 = reg.rd(0xC0)
    print("== reg 0x400C0000 : +0x84 = 0x%08X (期望 0x%08X = rans_top)" % (v84, VER_EXPECT))
    print("                     +0xC0 = 0x%08X (期望 0x%08X = stock reg_ctrl)" % (vc0, ADD_VER))
    if v84 != VER_EXPECT:
        print("*** 拒绝继续：+0x84 不是 rans_top 的版本号，PL 里不是我们的位流 ***")
        return 3

    print("== img=%s  source=%s  q=%s" % (img, hdr.get("SOURCE", "?"), hdr.get("Q_INDEX", "?")))

    streams = []
    cyc_total = 0
    t_all0 = time.perf_counter()

    for k in range(4):
        sym = np.fromfile("%s/p%d_sym.i32" % (args.dir, k), dtype=np.int32)
        scl = np.fromfile("%s/p%d_scales.f32" % (args.dir, k), dtype=np.float32)
        N = sym.size
        nbeat = (N + 15) // 16
        in_bytes = nbeat * 64
        out_off = in_bytes

        ki = build_index(scl)
        w = ((sym.astype(np.uint32) & 0xFFFF) << 16) | (ki & 0x3F)
        send = np.zeros(in_bytes + OUT_MAX_BYTES, dtype=np.uint8)
        send[:N * 4] = w.view(np.uint8)
        chunk.write(0, send.tobytes(), send.size)

        reg.wr(R_RBASE32, rbase)
        reg.wr(R_RSIZE, nbeat)
        reg.wr(R_WBASE32, rbase + out_off)
        reg.wr(R_NSYM, N)
        reg.wr(R_START, 1)

        polls = 0
        done = 0
        t0 = time.perf_counter()
        while polls < 20000000:
            done = reg.rd(R_DONE)
            polls += 1
            if done & 1:
                break
            if (polls & 0x3FF) == 0 and (time.perf_counter() - t0) > args.timeout:
                break
        wall_ms = (time.perf_counter() - t0) * 1000.0

        status = reg.rd(R_STATUS)
        plw = reg.rd(R_PLWORDS) & 0xFFFF
        cyc = reg.rd(R_CYC)
        nsym_rb = reg.rd(R_NSYM_R) & 0xFFFF
        nesc = reg.rd(R_NESC)
        nb = reg.rd(R_NBYP)
        if plw == 0 or plw > 16384:
            print("   ** phase %d pl_words=%u 不合理 **" % (k, plw))
            return 4
        raw = bytearray(plw * 4)
        chunk.read(raw, out_off, plw * 4)
        pay = bytes(raw)
        streams.append(pay)
        cyc_total += cyc
        print("   phase %d: %6d 符号 -> %5d B  cyc=%u  nsym_rb=%u  status=0x%08X"
              "  escape=%u bypass=%u  polls=%d wall=%.1fms"
              % (k, N, len(pay), cyc, nsym_rb, status, nesc, nb, polls, wall_ms))

    enc_wall_ms = (time.perf_counter() - t_all0) * 1000.0

    # ---- z 段 ----
    zidx = np.fromfile("%s/z_indices.i32" % args.dir, dtype=np.int32)
    zpay = pack_fixed_width(zidx.tolist(), Z_INDEX_BITS)
    zwant = (zidx.size * Z_INDEX_BITS + 7) // 8
    if len(zpay) != zwant:
        print("** z 段长度 %d != %d **" % (len(zpay), zwant))
        return 4
    print("== z 段: %d 索引 -> %d B (14 bit 定长)  最大索引 %d"
          % (zidx.size, len(zpay), int(zidx.max())))

    # ---- 头 76 B ----
    hb = struct.pack(">4sBBH", b"GLC2", int(hdr["VERSION"]), int(hdr["Q_INDEX"]), 0)
    for key in ("ORIG_H", "ORIG_W", "PAD_H", "PAD_W", "Y_C", "Y_H", "Y_W",
                "Z_C", "Z_H", "Z_W"):
        hb += struct.pack(">I", int(hdr[key]))
    hb += struct.pack(">I", int(zidx.size))
    hb += struct.pack(">I", len(zpay))
    for k in range(4):
        hb += struct.pack(">I", len(streams[k]))
    hb += struct.pack(">I", 0)
    if len(hb) != HEADER_SIZE:
        print("** 头长度 %d != %d **" % (len(hb), HEADER_SIZE))
        return 4

    blob = hb + zpay + b"".join(streams)
    with open(out_path, "wb") as f:
        f.write(blob)

    print()
    print("================ 板端 PL 自产容器 ================")
    print("  %s : %d B  md5=%s" % (out_path, len(blob), md5(blob)))
    print("  组成: 头 %d + z %d + 4 流 %s = %d"
          % (HEADER_SIZE, len(zpay), [len(s) for s in streams],
             HEADER_SIZE + len(zpay) + sum(len(s) for s in streams)))
    print("  PL 熵编码实测: %d 拍 = %.3f ms @%.0fMHz (wall %.1f ms)"
          % (cyc_total, cyc_total / HP_CLK_MHZ / 1000.0, HP_CLK_MHZ, enc_wall_ms))
    print("  压缩比: payload %d B -> %.6f bpp ; 整容器 %d B -> %.6f bpp"
          % (sum(len(s) for s in streams),
             8.0 * sum(len(s) for s in streams) / 65536.0,
             len(blob), 8.0 * len(blob) / 65536.0))

    rc = 0
    if os.path.exists(ref_path):
        ref = open(ref_path, "rb").read()
        same = (ref == blob)
        print()
        print("================ 与 A53 CPU 容器逐字节比对 ================")
        print("  参考(A53 glc2_pack) %s : %d B  md5=%s" % (ref_path, len(ref), md5(ref)))
        print("  板端 PL 自产         %s : %d B  md5=%s" % (out_path, len(blob), md5(blob)))
        if same:
            print("  ==> 逐字节一致 ==== PL 熵编码器完全顶替了 CPU 的 rANS 核 ====")
        else:
            rc = 1
            n = min(len(ref), len(blob))
            i = 0
            while i < n and ref[i] == blob[i]:
                i += 1
            print("  ==> ** 不一致 ** 首个不同字节 @%d : PL=%s REF=%s"
                  % (i, blob[i:i + 1].hex() if i < len(blob) else "-",
                     ref[i:i + 1].hex() if i < len(ref) else "-"))
            # 分段定位
            zend = HEADER_SIZE + len(zpay)
            print("      头段 %s / z 段 %s / 流段 %s"
                  % ("OK" if ref[:HEADER_SIZE] == blob[:HEADER_SIZE] else "差异",
                     "OK" if ref[HEADER_SIZE:zend] == blob[HEADER_SIZE:zend] else "差异",
                     "OK" if ref[zend:] == blob[zend:] else "差异"))
    else:
        print("\n  (无参考容器 %s，跳过比对)" % ref_path)

    return rc


if __name__ == "__main__":
    sys.exit(main())
