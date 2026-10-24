#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rans_py.py —— 板端：用 Python 把 GLC 的 (symbols, scales) 交给 PL 的 rANS 熵编码器

为什么要有这个文件（而不是继续用 C 的 rans_board）：
  ⚠️ **实测（2026-09-26）**：自定义算子的 DMA 只能看到 icraft 运行时分配的
  PL-DDR，**CPU 用 /dev/mem 摸不到那块内存**：
      运行时 malloc 得到 chunk addr = 4096；chunk 里写 0xDEADBEEF / 0x12345678；
      `devmem 0x80001000` → 0xAAAABBBB、`devmem 0x80001004` → 0xAAAABBBB（固定错误签名，
      不随数据变），`devmem 0x80000000` → 0xBAAAAAAA。
      ⇒ 必须走运行时 API 才能把数据放到算子看得见的地方。

  ⚠️ 另一条实测：`icraft.xrt` 的 `RegRegion.read(addr, relative=False)` 对**任何**地址
  都返回同一个常量（实测 0x2604080A），**它不是绝对地址读**。
  官方 `adder_demo.cpp` 正是用它来"等 done"的 ⇒ done 永远非零 ⇒ 循环立刻退出
  ⇒ **官方 adder demo 自己算出垃圾就是这个原因**。
  ⇒ 所以**寄存器访问改用 `mmap /dev/mem`**（已实测正确：读到 `+0x84 = 0x20260922`）。

分工：
    内存   : icraft.xrt 的 defaultMemRegion().malloc() + chunk.write/read
    寄存器 : mmap /dev/mem  @ 0x400C0000

判据（不需要自己实现 rANS）：
    `board_img0.glc` 的 4 个 stage payload 已被证明与官方 CPU encode() **逐字节一致**，
    所以直接拿它当参考对拍 PL 的输出。

用法：
    python3 rans_py.py                # 四相全跑
    python3 rans_py.py --phase 1      # 只跑 phase 1
"""
import argparse
import mmap
import os
import struct
import sys
import time

import numpy as np

REG_BASE = 0x400C0000
REG_LEN = 0x2000

# rans_top.v 的 RFU 寄存器映射（与 工具/板端程序/README.md 一致）
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

VER_EXPECT = 0x20260922   # rans_top 的 RFU_R0
ADD_VER = 0x20230628      # stock reg_ctrl 的 ADD_VERSION

HP_CLK_MHZ = 200.0        # hp_clk = ddr_clk = MIG ui_clk（实测）

GLC_HEADER_BYTES = 76     # >4sBBH17I == 4+1+1+2+17*4；不是 44
OUT_MAX_BYTES = 16384 * 4

# glc_cdf_table.h:40,43-60 —— 逐字抄，dtype=float32 保证与 C++ 的 float 比较逐位一致
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
    sc = np.where(sc > GLC_SCALE_BOUND, sc, GLC_SCALE_BOUND)   # !(scale > bound) -> bound
    cnt = (sc[:, None] <= GLC_SCALE_TABLE[None, :63]).sum(axis=1)
    return (63 - cnt).astype(np.uint32)


def parse_glc(path):
    blob = open(path, "rb").read()
    if blob[:4] != b"GLC2":
        raise SystemExit("not a GLC2 file: %s" % path)

    def be32(o):
        return int.from_bytes(blob[o:o + 4], "big")

    z_bytes = be32(52)
    stage_len = [be32(56 + 4 * i) for i in range(4)]
    off = GLC_HEADER_BYTES + z_bytes
    stage_off = []
    for i in range(4):
        stage_off.append(off)
        off += stage_len[i]
    if off != len(blob):
        print("  WARN 容器长度不自洽: %d vs %d" % (off, len(blob)))
    return blob, stage_len, stage_off


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
    ap.add_argument("--phase", type=int, default=-1)
    ap.add_argument("--dir", default="/root/glc/pack/img0")
    ap.add_argument("--glc", default="/root/glc/pack/img0.glc")
    ap.add_argument("--timeout", type=float, default=10.0)
    args = ap.parse_args()

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
        print("*** 拒绝继续：+0x84 不是 rans_top 的版本号，说明 PL 里不是我们的位流 ***")
        return 3

    blob, stage_len, stage_off = parse_glc(args.glc)
    print("== .glc = %s (%d B), stage 长度 %s" % (args.glc, len(blob), stage_len))

    phases = range(4) if args.phase < 0 else [args.phase]
    n_ok = 0
    n_ph = 0
    pl_cyc_total = 0
    for p in phases:
        n_ph += 1
        sym = np.fromfile("%s/p%d_sym.i32" % (args.dir, p), dtype=np.int32)
        scl = np.fromfile("%s/p%d_scales.f32" % (args.dir, p), dtype=np.float32)
        N = sym.size
        nbeat = (N + 15) // 16
        in_bytes = nbeat * 64
        out_off = in_bytes
        print("\n---- phase %d : %d 符号 (nbeat=%d, in_bytes=%d) ----" % (p, N, nbeat, in_bytes))

        k = build_index(scl)
        w = ((sym.astype(np.uint32) & 0xFFFF) << 16) | (k & 0x3F)
        send = np.zeros(in_bytes + OUT_MAX_BYTES, dtype=np.uint8)
        send[:N * 4] = w.view(np.uint8)
        t0 = time.perf_counter()
        chunk.write(0, send.tobytes(), send.size)
        t_flush = time.perf_counter() - t0

        reg.wr(R_RBASE32, rbase)
        reg.wr(R_RSIZE, nbeat)
        reg.wr(R_WBASE32, rbase + out_off)
        reg.wr(R_NSYM, N)
        t0 = time.perf_counter()
        reg.wr(R_START, 1)
        polls = 0
        done = 0
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
        nesc = reg.rd(R_NESC)
        nb = reg.rd(R_NBYP)
        cyc = reg.rd(R_CYC)
        maxnb = reg.rd(R_MAXNB) & 0x1F
        nsym_rb = reg.rd(R_NSYM_R) & 0xFFFF
        tfed = reg.rd(R_TFED) & 0xFFFFF
        print("   PL: done=%d polls=%d status=0x%08X pl_words=%u nsym_rb=%u cyc=%u" %
              (done & 1, polls, status, plw, nsym_rb, cyc))
        print("       n_escape=%u n_bypass=%u max_n_bypass=%u {tstate,fed}=%05X" %
              (nesc, nb, maxnb, tfed))
        print("       flush=%.1f ms  wall=%.1f ms  cyc=%.3f ms @%.0fMHz" %
              (t_flush * 1000.0, wall_ms, cyc / HP_CLK_MHZ / 1000.0, HP_CLK_MHZ))

        if plw == 0 or plw > 16384:
            print("   ** pl_words 不合理，跳过对拍 **")
            continue
        raw = bytearray(plw * 4)
        chunk.read(raw, out_off, plw * 4)
        pb = np.frombuffer(bytes(raw), dtype=np.uint8)
        ref = np.frombuffer(blob[stage_off[p]:stage_off[p] + stage_len[p]], dtype=np.uint8)
        same = (pb.size == ref.size) and bool(np.array_equal(pb, ref))
        print("   PL = %d B / 参考(stage%d) = %d B -> %s" %
              (pb.size, p, ref.size, "==== 逐字节一致 ====" if same else "** 不一致 **"))
        if not same:
            n = min(pb.size, ref.size)
            i = 0
            while i < n and pb[i] == ref[i]:
                i += 1
            print("       首个不同字节 @%d : PL=%02x REF=%02x" %
                  (i, pb[i] if i < pb.size else 0, ref[i] if i < ref.size else 0))
        else:
            n_ok += 1
        pl_cyc_total += cyc
        with open("/root/glc/pack/pl_py_p%d.bin" % p, "wb") as f:
            f.write(bytes(pb))
        print("       -> /root/glc/pack/pl_py_p%d.bin" % p)

    print("\n================ 汇总 ================")
    print("  相位逐字节一致 : %d / %d" % (n_ok, n_ph))
    print("  PL 实测拍数合计: %d 拍 = %.3f ms @%.0fMHz" %
          (pl_cyc_total, pl_cyc_total / HP_CLK_MHZ / 1000.0, HP_CLK_MHZ))
    enc = sum(stage_len)
    print("  压缩比 payload : %d B / (256*256) = %.6f bpp" % (enc, 8.0 * enc / 65536.0))
    print("  压缩比 整容器  : %d B -> %.6f bpp" % (len(blob), 8.0 * len(blob) / 65536.0))
    return 0 if n_ok == n_ph else 1


if __name__ == "__main__":
    sys.exit(main())
