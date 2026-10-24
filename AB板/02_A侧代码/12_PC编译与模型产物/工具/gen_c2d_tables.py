# -*- coding: utf-8 -*-
r"""从官方 `assets\板端代码\glc_cdf_table.h` 解析出 C2d 需要的 ROM 初始化文件。

产出（写入 `C2_PL熵编码器\mem\`）：
    cdf_flat.hex    27256 × 32bit   CDF 累积值（紧凑排列）
    row_start.hex      64 × 32bit   每行在 CDF_FLAT 中的起始下标
    cdf_len.hex        64 × 32bit   每行长度（GLC_CDF_LENGTH）
    cdf_off.hex        64 × 32bit   每行偏移（GLC_CDF_OFFSET，按补码存）
    rcp_arr.hex     27256 × 64bit   与 CDF_FLAT **同址**的倒数表：
                                    rcp_arr[row_start[k]+v] = (2^64-1) / (cdf[v+1]-cdf[v])
    scale_tbl.hex      64 × 32bit   glc_build_index 用的 scale 表（默认放 PS，这里留档）

口径来源：`C2_PL熵编码器\设计规格.md` §五；算法基线 `glc_board_encoder.h:97-175`。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SRC = os.path.join(REPO, "assets", "板端代码", "glc_cdf_table.h")
OUT = os.path.join(REPO, "C2_PL熵编码器", "mem")


def parse_array(text, name, as_float=False):
    """抓 `static const <type> NAME[...] = { ... };` 里的数字（十进制/十六进制）。"""
    m = re.search(re.escape(name) + r"\s*\[[^\]]*\]\s*=\s*\{(.*?)\}\s*;", text, re.S)
    if not m:
        raise SystemExit("找不到数组 %s" % name)
    body = m.group(1)
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    body = re.sub(r"//[^\n]*", "", body)
    toks = [t.strip() for t in body.split(",") if t.strip()]
    if as_float:
        # float 数组：转成 float32 的位模式（与 C 里 static const float 一致）
        import struct
        out = []
        for t in toks:
            t = t.rstrip("fF")
            out.append(struct.unpack("<I", struct.pack("<f", float(t)))[0])
        return out
    return [int(t, 0) for t in toks]


def main():
    txt = open(SRC, encoding="utf-8", errors="replace").read()

    length = parse_array(txt, "GLC_CDF_LENGTH")
    offset = parse_array(txt, "GLC_CDF_OFFSET")
    row_start = parse_array(txt, "GLC_ROW_START")
    flat = parse_array(txt, "GLC_CDF_FLAT")
    scale_tbl = parse_array(txt, "GLC_SCALE_TABLE", as_float=True)

    n_cdfs = int(re.search(r"#define\s+GLC_NUM_CDFS\s+(\d+)", txt).group(1))
    entries = int(re.search(r"#define\s+GLC_CDF_ENTRIES\s+(\d+)", txt).group(1))
    print("解析: NUM_CDFS=%d  ENTRIES=%d" % (n_cdfs, entries))
    print("  实际长度: len=%d offset=%d row_start=%d flat=%d scale=%d"
          % (len(length), len(offset), len(row_start), len(flat), len(scale_tbl)))
    assert len(length) == len(offset) == len(row_start) == n_cdfs
    assert len(flat) == entries, "flat 项数 %d != %d" % (len(flat), entries)
    assert len(scale_tbl) == n_cdfs

    # ---- 自检：每行最后一个必须是 2^16，行起始与长度自洽 ----
    for k in range(n_cdfs):
        s, ln = row_start[k], length[k]
        assert s + ln <= entries, "行 %d 越界" % k
        assert flat[s + ln - 1] == 65536, "行 %d 末项应为 65536，实际 %d" % (k, flat[s + ln - 1])
        if k + 1 < n_cdfs:
            assert row_start[k + 1] == s + ln, "行 %d/%d 起始不连续" % (k, k + 1)
    print("  自检：64 行末项均为 65536、行起始连续 ✅")

    os.makedirs(OUT, exist_ok=True)

    def w(name, lines):
        p = os.path.join(OUT, name)
        with open(p, "w", encoding="ascii", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
        return p, os.path.getsize(p)

    w("cdf_flat.hex", ["%08x" % v for v in flat])
    w("row_start.hex", ["%08x" % v for v in row_start])
    w("cdf_len.hex", ["%08x" % v for v in length])
    w("cdf_off.hex", ["%08x" % (v & 0xFFFFFFFF) for v in offset])
    w("scale_tbl.hex", ["%08x" % v for v in scale_tbl])

    # ---- 倒数表：与 CDF_FLAT **同址** ----
    # 对每一项下标 i = row_start[k]+v，它对应的 range = cdf[v+1]-cdf[v]，
    # 倒数 rcp = (2^64-1) // range  （range>=1 恒成立）
    MASK64 = (1 << 64) - 1
    rcp = [0] * entries
    distinct = {}
    for k in range(n_cdfs):
        s, ln = row_start[k], length[k]
        for v in range(ln - 1):
            rng = flat[s + v + 1] - flat[s + v]
            assert rng >= 1, "行 %d v=%d range=%d" % (k, v, rng)
            r = MASK64 // rng
            rcp[s + v] = r
            distinct.setdefault(rng, r)
    w("rcp_arr.hex", ["%016x" % v for v in rcp])

    # ---- BRAM 估算（Xilinx 36Kb BRAM，Zynq-7030 共 265 个 ≈ 9.54 Mb）----
    cdf_bits = entries * 32
    rcp_bits = entries * 64
    ctl_bits = n_cdfs * 32 * 3
    tot = cdf_bits + rcp_bits + ctl_bits
    print("\n不同 range 值个数 = %d" % len(distinct))
    print("  CDF_FLAT  %8d bit = %.3f Mb" % (cdf_bits, cdf_bits / 1048576))
    print("  RCP(同址) %8d bit = %.3f Mb" % (rcp_bits, rcp_bits / 1048576))
    print("  控制表    %8d bit = %.3f Mb" % (ctl_bits, ctl_bits / 1048576))
    print("  合计      %8d bit = %.3f Mb  = 9.54 Mb 的 %.1f%%"
          % (tot, tot / 1048576, tot / (265 * 36864) * 100))
    print("\n产出目录: %s" % OUT)
    for f in sorted(os.listdir(OUT)):
        print("  %-16s %9d B" % (f, os.path.getsize(os.path.join(OUT, f))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
