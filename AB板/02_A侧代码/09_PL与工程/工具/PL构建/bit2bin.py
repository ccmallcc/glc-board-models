#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""bit2bin.py —— 把 Xilinx .bit 文件转成裸配置位流 .bin（fpga_manager 要的格式）

【为什么要这一步】
  板子上的加载流程是：
      echo xxx.bin > /sys/class/fpga_manager/fpga0/firmware
  它吃的是**裸位流**，而 Vivado/Procise 产出的是带头的 .bit。
  实测对照（同一设计）：
      ai7030_edif_top_disable_icap.bit  5,980,609 B
      ai7030_top_disable_icap.bin       5,980,460 B   ← 差 149 B
  差的正是 .bit 的文件头。

【.bit 文件结构】
  固定头 13 字节： 00 09 0F F0 0F F0 0F F0 0F F0 00 00 01
  随后是若干"字段"： 1 字节 tag + 长度 + 数据
      'a' 设计名    (2 字节长度)
      'b' 器件型号  (2 字节长度)
      'c' 日期      (2 字节长度)
      'd' 时间      (2 字节长度)
      'e' 位流数据  (**4 字节长度**)  ← 这一段就是 .bin 的内容
  长度都是**大端**。

用法：
    python bit2bin.py <in.bit> [out.bin]
    python bit2bin.py --info <in.bit>      # 只打印头部字段，不写文件
"""
import struct
import sys


def parse_bit(path):
    b = open(path, "rb").read()
    if len(b) < 13 or b[0:2] != b"\x00\x09":
        raise SystemExit("不是 Xilinx .bit 文件（头两字节应为 00 09）")
    pos = 13
    fields = {}
    while pos < len(b):
        tag = chr(b[pos])
        if tag == "e":
            ln = struct.unpack(">I", b[pos + 1:pos + 5])[0]
            head = 5
        else:
            ln = struct.unpack(">H", b[pos + 1:pos + 3])[0]
            head = 3
        data = b[pos + head:pos + head + ln]
        if len(data) != ln:
            raise SystemExit("字段 %r 被截断：期望 %d 实得 %d" % (tag, ln, len(data)))
        fields[tag] = data
        pos += head + ln
        if tag == "e":
            break
    if "e" not in fields:
        raise SystemExit("没找到 'e' 字段（位流数据）")
    return fields, pos, len(b)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    info_only = "--info" in sys.argv
    if not args:
        raise SystemExit(__doc__)
    path = args[0]
    f, end, total = parse_bit(path)

    def s(tag):
        return f.get(tag, b"").decode("ascii", "replace").rstrip("\x00")

    print("=" * 74)
    print("  %s" % path)
    print("=" * 74)
    print("  设计名   : %s" % s("a"))
    print("  器件     : %s" % s("b"))
    print("  日期/时间: %s %s" % (s("c"), s("d")))
    print("  头部长度 : %d 字节" % (end - len(f["e"])))
    print("  位流数据 : %d 字节" % len(f["e"]))
    print("  文件总长 : %d 字节（头 %d + 位流 %d = %d，剩余 %d）"
          % (total, end - len(f["e"]), len(f["e"]), end, total - end))
    print("  位流前 16 字节: %s" % " ".join("%02X" % x for x in f["e"][:16]))

    if info_only:
        return
    out = args[1] if len(args) > 1 else path.rsplit(".", 1)[0] + ".bin"
    payload = f["e"]

    # ★★ fpga_manager 要的是**字节交换过**的 .bin
    #   实测（2026-10-14）：直接喂 payload 会被拒：
    #     fpga_manager fpga0: Invalid bitstream, could not find a sync word.
    #                         Bitstream must be a byte swapped .bin file
    #   变换规则 = **每 4 字节组内反转**。逐字节对照（payload vs 板上能用的 .bin）：
    #     payload            板上 .bin
    #     00 00 00 BB    ->  BB 00 00 00     (总线宽度探测字)
    #     11 22 00 44    ->  44 00 22 11
    #     AA 99 55 66    ->  66 55 99 AA     (同步字)
    #     30 02 20 01    ->  01 20 02 30
    if len(payload) % 4 != 0:
        raise SystemExit("位流长度 %d 不是 4 的倍数，无法按 4 字节交换" % len(payload))
    if "--no-swap" in sys.argv:
        data = payload
        note = "（未交换，--no-swap）"
    else:
        ba = bytearray(len(payload))
        ba[0::4] = payload[3::4]
        ba[1::4] = payload[2::4]
        ba[2::4] = payload[1::4]
        ba[3::4] = payload[0::4]
        data = bytes(ba)
        note = "（已按 4 字节交换，fpga_manager 需要）"
    open(out, "wb").write(data)
    print("  ==> 已写出 %s（%d 字节）%s" % (out, len(data), note))
    print("      前 16 字节: %s" % " ".join("%02X" % x for x in data[:16]))
    print("      0x20 处 16 字节: %s" % " ".join("%02X" % x for x in data[0x20:0x30]))
    print("      0x30 处 16 字节: %s   <- 应看到同步字 66 55 99 AA" %
          " ".join("%02X" % x for x in data[0x30:0x40]))


if __name__ == "__main__":
    main()
