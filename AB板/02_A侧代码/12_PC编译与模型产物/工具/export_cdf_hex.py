#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_cdf_hex.py —— 把 `assets/板端代码/glc_cdf_table.h` 导出成
Verilog `$readmemh` 能读的十六进制文件，供 C2d（CDF BRAM + 符号映射 + 倒数表）的仿真用。

产出（默认写到 `E:\\fudanwei\\_logs\\rans\\`，可用第 1 个参数改目录）：
    cdf_flat.hex      27256 行，每行 8 位 hex（CDF 累积频率，≤ 2^16）
    cdf_row_start.hex    64 行，行起始偏移
    cdf_length.hex       64 行，每行项数
    cdf_offset.hex       64 行，每行符号偏移（**有符号**，写成 32 位补码）
    recip_by_f.hex    65536 行，每行 16 位 hex；recip[f] = (2^64-1)/f
                      （索引 0 保留为 0；f=1 → 2^64-1；这就是 RTL 要用的那个定义）

用法：
    python3 /mnt/e/fudanwei/GLC-共享包/工具/export_cdf_hex.py [输出目录]
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HDR = os.path.join(ROOT, "assets", "板端代码", "glc_cdf_table.h")

DEFAULT_OUT = "/mnt/e/fudanwei/_logs/rans"
if not os.path.isdir(DEFAULT_OUT):
    DEFAULT_OUT = os.path.join(os.path.dirname(ROOT), "_logs", "rans")

M64 = (1 << 64) - 1


def parse_array(txt, name, signed=False):
    m = re.search(re.escape(name) + r"\s*\[[^\]]*\]\s*=\s*\{(.*?)\};", txt, re.S)
    if not m:
        raise SystemExit("找不到数组 " + name)
    body = m.group(1)
    pat = r"-?\d+" if signed else r"\b\d+\b"
    return [int(v) for v in re.findall(pat, body)]


def dump(path, values, width, signed=False):
    with open(path, "w") as f:
        for v in values:
            if signed and v < 0:
                v = v + (1 << width)
            f.write("%0*x\n" % (width // 4, v))
    return len(values)


def main(argv):
    outdir = argv[1] if len(argv) > 1 else DEFAULT_OUT
    os.makedirs(outdir, exist_ok=True)

    txt = open(HDR, encoding="utf-8", errors="replace").read()
    flat = parse_array(txt, "GLC_CDF_FLAT")
    rstart = parse_array(txt, "GLC_ROW_START")
    clen = parse_array(txt, "GLC_CDF_LENGTH")
    off = parse_array(txt, "GLC_CDF_OFFSET", signed=True)

    assert len(flat) == 27256, len(flat)
    assert len(rstart) == 64 and len(clen) == 64 and len(off) == 64

    print("来源 : %s" % HDR)
    print("输出 : %s" % outdir)
    print()

    n = dump(os.path.join(outdir, "cdf_flat.hex"), flat, 32)
    print("cdf_flat.hex      %6d 行  最大 %d (应 == 65536 且末项为它)" % (n, max(flat)))
    n = dump(os.path.join(outdir, "cdf_row_start.hex"), rstart, 32)
    print("cdf_row_start.hex %6d 行  最大 %d" % (n, max(rstart)))
    n = dump(os.path.join(outdir, "cdf_length.hex"), clen, 32)
    print("cdf_length.hex    %6d 行  范围 %d ~ %d" % (n, min(clen), max(clen)))
    n = dump(os.path.join(outdir, "cdf_offset.hex"), off, 32, signed=True)
    print("cdf_offset.hex    %6d 行  范围 %d ~ %d（有符号，补码写出）" % (n, min(off), max(off)))

    # 倒数表：按 freq 直接索引（65,536 项，每项 64 位）—— 仿真用，真机再谈分级
    recip = [0] * 65536
    for f in range(1, 65536):
        recip[f] = M64 // f
    n = dump(os.path.join(outdir, "recip_by_f.hex"), recip, 64)
    print("recip_by_f.hex    %6d 行  recip[1]=%016x  recip[65533]=%016x"
          % (n, recip[1], recip[65533]))

    # 自检：recip 必须满足 rcp*f <= 2^64-1 < (rcp+1)*f
    bad = 0
    for f in (1, 2, 3, 7, 65533, 65535):
        r = recip[f]
        if not (r * f <= M64 < (r + 1) * f):
            bad += 1
    print()
    print("倒数表自检（f=1/2/3/7/65533/65535）: %s" % ("全过 PASS" if bad == 0 else "失败 %d" % bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
