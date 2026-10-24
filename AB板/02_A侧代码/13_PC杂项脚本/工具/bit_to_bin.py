#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 FMSH/Xilinx 的 .bit 转成 Linux FPGA manager 能加载的 .bin。

转换 = 去掉 .bit 头 + 按 32 位字做字节反序（即 bootgen -process_bitstream bin 的效果，
也就是 u-boot `fpga loadb` 里那个 byte-swap 的含义）。

【板上实测校验，2026-09-22】
  板上 /lib/firmware/ai7030_top_disable_icap.bin   (5,980,460 B)
  == swap32( 启动分区 ai7030_top_disable_icap.bit[144:] )
  全长 5,980,460 字节逐字节相同，0 处不同。

热加载命令（板上）：
  cp <name>.bin /lib/firmware/
  echo <name>.bin > /sys/class/fpga_manager/fpga0/firmware
  cat /sys/class/fpga_manager/fpga0/state        # 应仍为 operating
  dmesg | tail -1                                 # 应见 "writing <name>.bin to FMSH FMQL FPGA Manager"
"""
import struct
import sys

MAGIC = bytes([0x00, 0x09, 0x0F, 0xF0, 0x0F, 0xF0, 0x0F, 0xF0, 0x0F, 0xF0, 0x00, 0x00, 0x01])
SHORT_FIELDS = [b"a", b"b", b"c", b"d"]


def parse_bit_header(buf: bytes):
    """返回 (字段字典, 数据起始偏移)。头结构不合法就抛 ValueError。"""
    if not buf.startswith(MAGIC):
        raise ValueError("不是 .bit 文件：开头 13 字节魔数不匹配")
    off = len(MAGIC)
    fields = {}
    for tag in SHORT_FIELDS:
        if buf[off : off + 1] != tag:
            raise ValueError(
                "头结构异常：偏移 %d 处期望标签 %r，实际 %r" % (off, tag, buf[off : off + 1])
            )
        off += 1
        (n,) = struct.unpack(">H", buf[off : off + 2])
        off += 2
        fields[tag.decode()] = buf[off : off + n].decode("latin-1")
        off += n
    if buf[off : off + 1] != b"e":
        raise ValueError(
            "头结构异常：偏移 %d 处期望标签 'e'，实际 %r" % (off, buf[off : off + 1])
        )
    off += 1
    (data_len,) = struct.unpack(">I", buf[off : off + 4])
    off += 4
    fields["e_len"] = data_len
    return fields, off


def swap32(buf: bytes) -> bytes:
    """按 32 位字做字节反序。"""
    if len(buf) % 4:
        raise ValueError("位流数据长度 %d 不是 4 的倍数，无法按 32 位字反序" % len(buf))
    out = bytearray(len(buf))
    out[0::4] = buf[3::4]
    out[1::4] = buf[2::4]
    out[2::4] = buf[1::4]
    out[3::4] = buf[0::4]
    return bytes(out)


def bit_to_bin(buf: bytes):
    fields, off = parse_bit_header(buf)
    body = buf[off:]
    return fields, off, swap32(body)


def main() -> int:
    if len(sys.argv) != 3:
        print("用法: bit_to_bin.py <输入.bit> <输出.bin>")
        return 2
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, "rb") as f:
        buf = f.read()
    try:
        fields, off, body = bit_to_bin(buf)
    except ValueError as e:
        print("转换失败: %s" % e)
        return 1
    print("输入   : %s  (%d 字节)" % (src, len(buf)))
    print("  Design  : %s" % fields["a"])
    print("  Part    : %s" % fields["b"])
    print("  Date    : %s %s" % (fields["c"], fields["d"]))
    print("  头长度  : %d 字节" % off)
    ok = "一致" if len(buf) - off == fields["e_len"] else "不一致（请核对位流完整性）"
    print("  数据长度: %d 字节（头里声明 %d，%s）" % (len(buf) - off, fields["e_len"], ok))
    with open(dst, "wb") as f:
        f.write(body)
    print("输出   : %s  (%d 字节，= 去头 + 32 位字字节反序)" % (dst, len(body)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
