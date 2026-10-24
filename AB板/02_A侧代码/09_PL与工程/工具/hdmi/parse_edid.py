#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EDID 1.3/1.4 解析器 —— 只依赖标准库。

输出的关键部分是 **详细时序描述符（DTD）**：
FPGA 写 HDMI TX 需要的像素时钟 / 前肩 / 同步宽 / 后肩 / 极性，全在这里。
"""
import struct
import sys

ESTABLISHED = [
    (35, 7, 720, 400, 70), (35, 6, 720, 400, 88), (35, 5, 640, 480, 60),
    (35, 4, 640, 480, 67), (35, 3, 640, 480, 72), (35, 2, 640, 480, 75),
    (35, 1, 800, 600, 56), (35, 0, 800, 600, 60),
    (36, 7, 800, 600, 72), (36, 6, 800, 600, 75), (36, 5, 832, 624, 75),
    (36, 4, 1024, 768, 87), (36, 3, 1024, 768, 60), (36, 2, 1024, 768, 70),
    (36, 1, 1024, 768, 75), (36, 0, 1280, 1024, 75),
    (37, 7, 1152, 870, 75),
]
ASPECT = {0: "16:10", 1: "4:3", 2: "5:4", 3: "16:9"}

MANUF = {0: "", 1: "A", 2: "B", 3: "C", 4: "D", 5: "E", 6: "F", 7: "G", 8: "H",
         9: "I", 10: "J", 11: "K", 12: "L", 13: "M", 14: "N", 15: "O", 16: "P",
         17: "Q", 18: "R", 19: "S", 20: "T", 21: "U", 22: "V", 23: "W", 24: "X",
         25: "Y", 26: "Z"}


def decode_manufacturer(v):
    return (MANUF.get((v >> 10) & 0x1F, "?") + MANUF.get((v >> 5) & 0x1F, "?")
            + MANUF.get(v & 0x1F, "?"))


def parse_dtd(b):
    """18 字节详细时序描述符 -> dict"""
    pclk = struct.unpack_from("<H", b, 0)[0] * 10.0  # kHz
    if pclk == 0:
        return None
    ha = b[2] | ((b[4] & 0xF0) << 4)
    hb = b[3] | ((b[4] & 0x0F) << 8)
    va = b[5] | ((b[7] & 0xF0) << 4)
    vb = b[6] | ((b[7] & 0x0F) << 8)
    hfp = b[8] | ((b[11] & 0xC0) << 2)
    hsw = b[9] | ((b[11] & 0x30) << 4)
    vfp = ((b[10] & 0xF0) >> 4) | ((b[11] & 0x0C) << 2)
    vsw = (b[10] & 0x0F) | ((b[11] & 0x03) << 4)
    hbp = hb - hfp - hsw
    vbp = vb - vfp - vsw
    sync = (b[17] >> 3) & 0x03
    digital_sep = (sync == 3)
    return dict(
        pclk_khz=pclk,
        hactive=ha, hblank=hb, hfront=hfp, hsync=hsw, hback=hbp, htotal=ha + hb,
        vactive=va, vblank=vb, vfront=vfp, vsync=vsw, vback=vbp, vtotal=va + vb,
        hpol=("+" if (b[17] & 0x02) else "-"),
        vpol=("+" if (b[17] & 0x04) else "-"),
        digital_sep=digital_sep, sync_type=sync,
        interlaced=bool(b[17] & 0x80),
        hsize_mm=(b[12] | ((b[14] & 0xF0) << 4)),
        vsize_mm=(b[13] | ((b[14] & 0x0F) << 8)),
    )


def parse(path):
    d = open(path, "rb").read()
    print("=" * 78)
    print("文件: %s   (%d 字节 = %d 个 128B 块)" % (path, len(d), len(d) // 128))
    if d[:8] != b"\x00\xff\xff\xff\xff\xff\xff\x00":
        print("  !! 头不对，不是合法 EDID")
        return
    mfg = decode_manufacturer(struct.unpack_from(">H", d, 8)[0])
    prod = struct.unpack_from("<H", d, 10)[0]
    serial = struct.unpack_from("<I", d, 12)[0]
    week, year = d[16], d[17] + 1990
    ver, rev = d[18], d[19]
    vid = d[20]
    print("  厂商=%s  产品码=0x%04X  序列号=%d  生产=%d年第%d周" % (mfg, prod, serial, year, week))
    print("  EDID 版本 = %d.%d" % (ver, rev))

    if vid & 0x80:
        depth = {0: "undefined", 1: 6, 2: 8, 3: 10, 4: 12, 5: 14, 6: 16}.get((vid >> 4) & 7, "?")
        iface = {0: "undefined", 1: "DVI", 2: "HDMI-a", 3: "HDMI-b", 4: "MDDI", 5: "DisplayPort"}.get(vid & 0xF, "?")
        print("  输入 = 数字  位深=%s  接口=%s" % (depth, iface))
    else:
        print("  输入 = 模拟")
    print("  物理尺寸 = %d mm x %d mm  (%.1f\" 对角)"
          % (d[21], d[22], ((d[21] ** 2 + d[22] ** 2) ** 0.5) / 25.4 if d[21] and d[22] else 0))
    if d[23] != 0xFF:
        print("  Gamma = %.2f" % ((d[23] + 100) / 100.0))
    f = d[24]
    print("  特性: 待机=%d 挂起=%d 关机=%d sRGB=%d **首选时序含原生=%d** 连续频率=%d"
          % ((f >> 7) & 1, (f >> 6) & 1, (f >> 5) & 1, (f >> 2) & 1, (f >> 1) & 1, f & 1))

    print("  -- 已建立时序 (established timings) --")
    any_est = False
    for byte, bit, h, v, r in ESTABLISHED:
        if d[byte] & (1 << bit):
            print("     %dx%d @ %d Hz" % (h, v, r))
            any_est = True
    if not any_est:
        print("     （无）")

    print("  -- 标准时序 (standard timings) --")
    any_std = False
    for i in range(8):
        o = 38 + i * 2
        b0, b1 = d[o], d[o + 1]
        if b0 == 0x01 and b1 == 0x01:
            continue
        if b0 == 0 and b1 == 0:
            continue
        hact = (b0 + 31) * 8
        ar = ASPECT.get((b1 >> 6) & 3, "?")
        vf = (b1 & 0x3F) + 60
        print("     %d x ? (%s) @ %d Hz" % (hact, ar, vf))
        any_std = True
    if not any_std:
        print("     （无）")

    print("  -- 4 个 18 字节描述符 --")
    dtds = []
    for i in range(4):
        o = 54 + i * 18
        b = d[o:o + 18]
        if b[0] == 0 and b[1] == 0 and b[2] == 0:
            tag = b[3]
            txt = b[5:18].split(b"\x0a")[0].decode("ascii", "replace").strip()
            name = {0xFF: "序列号", 0xFE: "ASCII 串", 0xFC: "型号名",
                    0xFD: "范围限制", 0xFB: "附加白点", 0xFA: "附加标准时序",
                    0x10: "占位"}.get(tag, "标签0x%02X" % tag)
            if tag == 0xFD and len(b) >= 18:
                print("     [%d] %s: 垂直 %d-%d Hz, 水平 %d-%d kHz, 最大像素时钟 %d MHz"
                      % (i, name, b[5], b[6], b[7], b[8], b[9] * 10))
            else:
                print("     [%d] %s: \"%s\"" % (i, name, txt))
        else:
            t = parse_dtd(b)
            if t:
                dtds.append(t)
                print("     [%d] **详细时序** %dx%d @ %.2f Hz  像素时钟 %.2f MHz"
                      % (i, t["hactive"], t["vactive"],
                         t["pclk_khz"] * 1000.0 / (t["htotal"] * t["vtotal"]),
                         t["pclk_khz"] / 1000.0))
            else:
                print("     [%d] （无效 DTD）" % i)

    print("  扩展块数 = %d" % d[126])
    if d[126] > 0 and len(d) >= 256:
        e = d[128:256]
        print("  -- 扩展块 #1: tag=0x%02X rev=%d --" % (e[0], e[1]))
        if e[0] == 0x02:
            dtd_off = e[2]
            print("      CEA-861: 原生 DTD 数=%d, DTD 起始偏移=%d" % (e[2] & 0x0F, dtd_off))
            vic = []
            for k in range(4, min(dtd_off, 127) if dtd_off else 127):
                for j in range(8):
                    c = e[k]
                    if c == 0:
                        break
                    vic.append(c & 0x7F if k >= 4 else c)
                    if j == 7 and k >= 4:
                        break
            for k in range(4, (dtd_off if dtd_off else 127)):
                if e[k] == 0:
                    break
                for j in range(8):
                    c = e[k]
                    if c == 0:
                        break
                    if j == 0 and k == 4:
                        pass
            # 简化：直接抽 VIC 列表
            svd = []
            k = 4
            while k < (dtd_off if dtd_off else 127) and e[k] != 0:
                for j in range(8):
                    c = e[k]
                    if c == 0:
                        break
                    svd.append(c & 0x7F)
                    k += 1
                k += 1
            if svd:
                print("      支持 VIC: %s" % sorted(set(svd)))
            if dtd_off and dtd_off < 127:
                o = 128 + dtd_off
                t = parse_dtd(d[o:o + 18])
                if t:
                    dtds.append(t)
                    print("      **CEA DTD** %dx%d @ %.2f Hz  像素时钟 %.2f MHz"
                          % (t["hactive"], t["vactive"],
                             t["pclk_khz"] * 1000.0 / (t["htotal"] * t["vtotal"]),
                             t["pclk_khz"] / 1000.0))

    print()
    print("  ############ FPGA 需要的时序参数 ############")
    for n, t in enumerate(dtds):
        print("  --- 时序 %d : %dx%d ---" % (n, t["hactive"], t["vactive"]))
        print("      像素时钟 PCLK   = %.4f MHz  (%d kHz)" % (t["pclk_khz"] / 1000.0, int(t["pclk_khz"])))
        print("      行 H: active=%d  front=%d  sync=%d  back=%d  (blank=%d, total=%d)"
              % (t["hactive"], t["hfront"], t["hsync"], t["hback"], t["hblank"], t["htotal"]))
        print("      场 V: active=%d  front=%d  sync=%d  back=%d  (blank=%d, total=%d)"
              % (t["vactive"], t["vfront"], t["vsync"], t["vback"], t["vblank"], t["vtotal"]))
        print("      同步极性: HSync %s  VSync %s   帧率 %.3f Hz"
              % (t["hpol"], t["vpol"],
                 t["pclk_khz"] * 1000.0 / (t["htotal"] * t["vtotal"])))
        print("      数字分离同步 = %s   隔行 = %s"
              % ("是" if t["digital_sep"] else "否(复合同步)", "是" if t["interlaced"] else "否"))
        if t["hsize_mm"] and t["vsize_mm"]:
            print("      画面尺寸 = %d x %d mm" % (t["hsize_mm"], t["vsize_mm"]))


if __name__ == "__main__":
    for p in sys.argv[1:]:
        parse(p)
        print()
