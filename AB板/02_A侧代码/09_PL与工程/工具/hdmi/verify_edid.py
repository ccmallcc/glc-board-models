#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_edid.py —— EDID 逐字段核对（2026-10-14）

比 parse_edid.py 更"取证"：打印原始十六进制、逐字段手算、解码 CEA 扩展块的数据块集合。
只依赖标准库。用法：python verify_edid.py <edid.bin> [out.txt]
"""
import sys

MANUF = {i: c for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ", start=1)}
EST = [
    (35, 7, "720x400@70"), (35, 6, "720x400@88"), (35, 5, "640x480@60"),
    (35, 4, "640x480@67"), (35, 3, "640x480@72"), (35, 2, "640x480@75"),
    (35, 1, "800x600@56"), (35, 0, "800x600@60"),
    (36, 7, "800x600@72"), (36, 6, "800x600@75"), (36, 5, "832x624@75"),
    (36, 4, "1024x768@87i"), (36, 3, "1024x768@60"), (36, 2, "1024x768@70"),
    (36, 1, "1024x768@75"), (36, 0, "1280x1024@75"),
    (37, 7, "1152x870@75"),
]
VIC = {
    1: "640x480p60", 2: "720x480p60(4:3)", 3: "720x480p60(16:9)", 4: "1280x720p60",
    5: "1920x1080i60", 6: "720x480i60(4:3)", 7: "720x480i60(16:9)", 8: "720x240p60",
    9: "1920x1080i50", 10: "720x576i50", 11: "720x576i50", 12: "720x240p60",
    13: "720x240p60", 14: "1440x480p60", 15: "1440x480p60", 16: "1920x1080p60",
    17: "720x576p50", 18: "720x576p50", 19: "1280x720p50", 20: "1920x1080i50",
    21: "720x576p50", 22: "720x576p50", 23: "1440x576p50", 24: "1440x576p50",
    25: "1920x1080p50(2880x576i)", 26: "2880x480i60", 27: "2880x480i60",
    28: "2880x576i50", 29: "2880x576i50", 30: "1440x576p50", 31: "1920x1080p50",
    32: "1920x1080p24", 33: "1920x1080p25", 34: "1920x1080p30", 35: "2880x480p60",
    36: "2880x480p60", 37: "2880x576p50", 38: "2880x576p50", 39: "1920x1080i50",
    40: "1920x1080i100", 41: "1280x720p100", 46: "1920x1080i120", 47: "1280x720p120",
    60: "1280x720p24", 61: "1280x720p25", 62: "1280x720p30", 63: "1920x1080p120",
    64: "1920x1080p100", 78: "1440x480p60", 93: "3840x2160p24", 94: "3840x2160p25",
    95: "3840x2160p30", 96: "3840x2160p50", 97: "3840x2160p60",
}
DB_TAG = {1: "Audio", 2: "Video", 3: "Vendor Specific", 4: "Speaker Allocation",
          5: "VESA DTC", 6: "Extended", 7: "Use Extended Tag"}
EXT_TAG = {0: "Video Capability", 1: "Vendor Specific Video", 5: "Colorimetry",
           6: "HDR Static Metadata", 13: "Video Format Preference",
           14: "YCbCr 4:2:0 Video", 15: "YCbCr 4:2:0 Capability Map",
           17: "HEVC", 18: "VESA DTC"}


def dtd(b, o, out):
    pclk = ((b[o + 1] << 8) | b[o]) * 10
    if pclk == 0:
        return None
    ha = b[o + 2] | ((b[o + 4] >> 4) << 8)
    hb = b[o + 3] | ((b[o + 4] & 0x0F) << 8)
    va = b[o + 5] | ((b[o + 7] >> 4) << 8)
    vb = b[o + 6] | ((b[o + 7] & 0x0F) << 8)
    hfp = b[o + 8] | ((b[o + 11] >> 6 & 3) << 8)
    hsw = b[o + 9] | ((b[o + 11] >> 4 & 3) << 8)
    vfp = (b[o + 10] >> 4) | ((b[o + 11] >> 2 & 3) << 4)
    vsw = (b[o + 10] & 0x0F) | ((b[o + 11] & 3) << 4)
    hbp = hb - hfp - hsw
    vbp = vb - vfp - vsw
    hpol = "+" if (b[o + 17] >> 1) & 1 else "-"
    vpol = "+" if b[o + 17] & 1 else "-"
    hmm = b[o + 12] | ((b[o + 14] >> 4) << 8)
    vmm = b[o + 13] | ((b[o + 14] & 0x0F) << 8)
    inter = "i" if (b[o + 17] >> 7) & 1 else "p"
    fv = pclk * 1000.0 / ((ha + hb) * (va + vb))
    out.append("      像素时钟 PCLK = %.4f MHz  (%d kHz)" % (pclk / 1000.0, pclk))
    out.append("      H: active=%d front=%d sync=%d back=%d  (blank=%d total=%d)"
               % (ha, hfp, hsw, hbp, hb, ha + hb))
    out.append("      V: active=%d front=%d sync=%d back=%d  (blank=%d total=%d)"
               % (va, vfp, vsw, vbp, vb, va + vb))
    out.append("      极性 HSync %s / VSync %s ; 扫描 %s ; 帧率 %.3f Hz ; 尺寸 %d x %d mm"
               % (hpol, vpol, inter, fv, hmm, vmm))
    out.append("      ★ 图形 = %dx%d%s @ %.3f Hz, PCLK %.3f MHz"
               % (ha, va, inter, fv, pclk / 1000.0))
    return dict(pclk=pclk, ha=ha, va=va, hfp=hfp, hsw=hsw, hbp=hbp,
                vfp=vfp, vsw=vsw, vbp=vbp, hpol=hpol, vpol=vpol,
                htotal=ha + hb, vtotal=va + vb, fv=fv)


def main():
    path = sys.argv[1]
    b = open(path, "rb").read()
    out = []
    P = out.append
    P("=" * 78)
    P("EDID 逐字段核对：%s  (%d 字节 = %d 个 128B 块)" % (path, len(b), len(b) // 128))
    P("=" * 78)
    for k in range(len(b) // 128):
        blk = b[k * 128:(k + 1) * 128]
        s = sum(blk) & 0xFF
        P("\n--- 块 #%d 校验和：%02X，全块和 mod 256 = %d  %s"
          % (k, blk[127], s, "✅ 通过" if s == 0 else "❌ 失败"))
        for r in range(0, 128, 16):
            P("    %02X: %s" % (r, " ".join("%02X" % x for x in blk[r:r + 16])))

    P("\n" + "=" * 78)
    P("基础块 #0")
    P("=" * 78)
    m = (b[8] << 8) | b[9]
    P("  厂商码   : %s%s%s  (0x%04X)"
      % (MANUF.get((m >> 10) & 0x1F, "?"), MANUF.get((m >> 5) & 0x1F, "?"),
         MANUF.get(m & 0x1F, "?"), m))
    P("  产品码   : 0x%04X   序列号: 0x%08X"
      % (b[11] << 8 | b[10], int.from_bytes(b[12:16], "little")))
    P("  生产日期 : %d 年 第 %d 周   ★(EDID 1.3 的字节 17 = 年份 - 1990)"
      % (b[17] + 1990, b[16]))
    P("  EDID 版本: %d.%d" % (b[18], b[19]))
    P("  视频输入 : %02X -> %s" % (b[20], "数字" if b[20] & 0x80 else "模拟"))
    if b[20] & 0x80:
        dfps = (b[20] >> 1) & 0x0F
        P("             DFPS=0x%X -> %s" % (dfps, {0: "未定义", 1: "DVI", 2: "HDMI-a",
                                                  3: "HDMI-b", 4: "MDDI", 5: "DisplayPort"}.get(dfps, "?")))
    P("  物理尺寸 : %d cm x %d cm  -> 对角线约 %.1f 英寸  ★(EDID 单位是 cm，不是 mm)"
      % (b[21], b[22], ((b[21] ** 2 + b[22] ** 2) ** 0.5) / 2.54 if b[21] and b[22] else -1))
    P("  Gamma    : %.2f" % ((b[23] + 100) / 100.0))
    f = b[24]
    P("  特性字节 : %02X  电源管理(待机=%d 挂起=%d 关机=%d) sRGB=%d 首选时序原生=%d"
      % (f, f >> 7 & 1, f >> 6 & 1, f >> 5 & 1, f >> 2 & 1, f >> 1 & 1))
    P("  -- 已建立时序 --")
    for byte, bit, name in EST:
        if b[byte] >> bit & 1:
            P("     %s" % name)
    P("  -- 标准时序 --")
    any_std = False
    for i in range(38, 54, 2):
        if b[i] == 0x01 and b[i + 1] == 0x01:
            continue
        any_std = True
        h = (b[i] + 31) * 8
        ar = {0: "16:10", 1: "4:3", 2: "5:4", 3: "16:9"}[(b[i + 1] >> 6) & 3]
        P("     %dx? @ %d Hz  (%s)" % (h, (b[i + 1] & 0x3F) + 60, ar))
    if not any_std:
        P("     （无）")
    P("  -- 4 个 18 字节描述符 --")
    dtds = []
    for i in range(4):
        o = 54 + i * 18
        blk = b[o:o + 18]
        if blk[0] == 0 and blk[1] == 0:
            tag = blk[3]
            if tag == 0xFC:
                P("     [%d] 型号名   : \"%s\"" % (i, blk[5:18].decode("ascii", "replace").strip()))
            elif tag == 0xFF:
                P("     [%d] 序列号   : \"%s\"" % (i, blk[5:18].decode("ascii", "replace").strip()))
            elif tag == 0xFD:
                P("     [%d] 范围限制 : 垂直 %d-%d Hz, 水平 %d-%d kHz, 最大像素时钟 %d MHz"
                  % (i, blk[5], blk[6], blk[7], blk[8], blk[9] * 10))
            else:
                P("     [%d] 描述符 tag=0x%02X" % (i, tag))
            continue
        P("     [%d] **详细时序**" % i)
        d = dtd(b, o, out)
        if d:
            dtds.append(("基础块 DTD#%d" % i, d))
    P("  扩展块数 : %d" % b[126])

    for k in range(1, len(b) // 128):
        blk = b[k * 128:(k + 1) * 128]
        P("\n" + "=" * 78)
        P("扩展块 #%d  tag=0x%02X rev=%d" % (k, blk[0], blk[1]))
        P("=" * 78)
        if blk[0] != 0x02:
            P("  （非 CEA-861，跳过）")
            continue
        doff = blk[2]
        P("  CEA-861: 原生 DTD 数 = %d, DTD 起始偏移 = %d" % (blk[3] & 0x0F, doff))
        P("  特性标志 = 0x%02X  [bit7 支持欠扫描=%d  bit6 支持基本音频=%d  "
          "bit5 支持 YCbCr444=%d  bit4 支持 YCbCr422=%d]"
          % (blk[3], blk[3] >> 7 & 1, blk[3] >> 6 & 1, blk[3] >> 5 & 1, blk[3] >> 4 & 1))
        vi, n = 4, 0
        vics, dbs = [], []
        # ★ CEA-861 数据块头：bit7-5 = tag，bit4-0 = 长度（原来写反了，已修）
        while vi < doff and blk[vi] != 0:
            tg = (blk[vi] >> 5) & 0x07
            ln = blk[vi] & 0x1F
            body = blk[vi + 1:vi + 1 + ln]
            dbs.append((tg, ln, list(body)))
            if tg == 2:
                for x in body:
                    vics.append(x & 0x7F)
            vi += ln + 1
            n += 1
        P("  数据块集合（%d 个）:" % n)
        for tg, ln, body in dbs:
            P("     tag=%d (%-16s) len=%d  %s"
              % (tg, DB_TAG.get(tg, "?"), ln, " ".join("%02X" % x for x in body)))
            if tg == 3 and len(body) >= 3 and body[0] == 0x03 and body[1] == 0x0C and body[2] == 0x00:
                P("        ★ 这是 HDMI 1.4b Vendor Specific 块 -> 屏支持 HDMI（非纯 DVI）")
            if tg == 6 and body:
                P("        Extended tag = %d (%s)" % (body[0], EXT_TAG.get(body[0], "?")))
            if tg == 1:
                P("        音频: 最多 %d 个描述符" % (body[0] & 7))
        P("  支持 VIC (%d 个): %s" % (len(vics), vics))
        for v in vics:
            P("     VIC %-3d = %s" % (v, VIC.get(v, "?")))
        if doff and doff < 127:
            o = doff
            while o + 18 <= 127 and (blk[o] or blk[o + 1]):
                P("  **CEA DTD**")
                d = dtd(blk, o, out)
                if d:
                    dtds.append(("CEA DTD", d))
                o += 18

    P("\n" + "=" * 78)
    P("★★★ FPGA 需要的时序参数汇总 ★★★")
    P("=" * 78)
    for name, d in dtds:
        P("  [%s]  %dx%d %s  PCLK %.4f MHz" % (name, d["ha"], d["va"],
                                              "隔行" if False else "逐行", d["pclk"] / 1000.0))
    P("\n  ⚠️ 上面**没有任何 1024x800 的模式**；EDID 首选（原生）时序是 1024x600。")

    txt = "\n".join(out)
    if len(sys.argv) > 2:
        open(sys.argv[2], "w", encoding="utf-8").write(txt + "\n")
    else:
        try:
            print(txt)
        except UnicodeEncodeError:
            sys.stdout.buffer.write(txt.encode("utf-8", "replace"))


main()
