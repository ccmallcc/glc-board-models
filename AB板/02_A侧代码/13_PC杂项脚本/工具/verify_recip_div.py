#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_recip_div.py —— 验证 C2a2「倒数乘法 + 一次修正」除法方案的**精确性**。

这是 C2a2 的**验证凭据**：RTL 实现之前，先用 Python 大整数把算法本身证死。
它**不依赖任何 RTL**，只用 Python 自己的整数除法做对照。

方案（见 `C2_PL熵编码器\设计规格.md` §四 难点 1）：

    rcp = (2**64 - 1) // f          # 无符号 64 位整数除法，向下取整
    q0  = (x * rcp) >> 64           # 128 位乘积取高 64 位
    r0c = (x - q0 * f) mod 2**17    # 只保留低 17 位
    if r0c >= f:  q = q0 + 1, r = r0c - f
    else:         q = q0,     r = r0c
    断言  q == x//f  且  r == x%f

为什么一次修正就够（写进 RTL 注释的同一段理由）：
    设 2**64-1 = rcp*f + e，0 <= e < f，则
        x*rcp/2**64 = x/f - x*(e+1)/(f*2**64)
    误差项 < x/2**64 < 1（rANS 保证 x < 2**63），所以 q0 只可能是真商 Q 或 Q-1。
    又因为此时 x - q0*f < 2*f <= 131066 < 2**17，第二次乘法只需低位。

用法（WSL）：
    python3 /mnt/e/fudanwei/GLC-共享包/工具/verify_recip_div.py [divvec 路径]

退出码：0 = 全过，1 = 有失败。
"""
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)          # GLC-共享包
HDR = os.path.join(ROOT, "assets", "板端代码", "glc_cdf_table.h")

DIVVEC_CANDIDATES = [
    "/mnt/e/fudanwei/_logs/rans/divvec_p1.txt",
    "E:/fudanwei/_logs/rans/divvec_p1.txt",
    "E:\\fudanwei\\_logs\\rans\\divvec_p1.txt",
]

M64 = (1 << 64) - 1
M17 = (1 << 17) - 1


def parse_array(txt, name):
    m = re.search(re.escape(name) + r"\s*\[[^\]]*\]\s*=\s*\{(.*?)\};", txt, re.S)
    if not m:
        raise SystemExit("cannot find array " + name)
    return [int(v) for v in re.findall(r"\b\d+\b", m.group(1))]


def scheme(x, f):
    """返回 (q, r, q0, exact_r0, cor, r0_fits_17bit)。"""
    rcp = M64 // f
    q0 = (x * rcp) >> 64
    exact_r0 = x - q0 * f
    r0c = exact_r0 & M17
    cor = 1 if r0c >= f else 0
    q = q0 + cor
    r = r0c - f if cor else r0c
    return q, r, q0, exact_r0, cor, (0 <= exact_r0 < (1 << 17))


def find_divvec(argv):
    if len(argv) > 1:
        return argv[1] if os.path.exists(argv[1]) else None
    for p in DIVVEC_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def main(argv):
    print("=" * 72)
    print("PART A -- CDF 表结构（直接解析官方表头）")
    print("=" * 72)
    txt = open(HDR, encoding="utf-8", errors="replace").read()
    flat = parse_array(txt, "GLC_CDF_FLAT")
    rstart = parse_array(txt, "GLC_ROW_START")
    clen = parse_array(txt, "GLC_CDF_LENGTH")
    print("GLC_CDF_FLAT 项数 : %d (期望 27256)" % len(flat))
    print("行数              : %d / %d (期望 64)" % (len(rstart), len(clen)))
    assert len(flat) == 27256 and len(rstart) == 64 and len(clen) == 64

    struct_bad = []
    for k in range(64):
        if k + 1 < 64 and rstart[k] + clen[k] != rstart[k + 1]:
            struct_bad.append(("rowstart", k))
        row = flat[rstart[k]:rstart[k] + clen[k]]
        if row[-1] != 65536:
            struct_bad.append(("last!=65536", k, row[-1]))
        for i in range(len(row) - 1):
            if row[i + 1] <= row[i]:
                struct_bad.append(("not-strict", k, i))
                break
    print("结构问题          : %s" % (struct_bad if struct_bad else "无"))

    allr = []
    for k in range(64):
        row = flat[rstart[k]:rstart[k] + clen[k]]
        for i in range(len(row) - 1):
            allr.append(row[i + 1] - row[i])
    print("(start,range) 对数: %d (期望 27192)" % len(allr))
    print("range 最小 / 最大 : %d / %d" % (min(allr), max(allr)))
    print("不同 range 值个数 : %d   <-- 倒数表分级方案只需这么多项" % len(set(allr)))
    print("是否出现 65536    : %s" % ("是 —— uint16 会变 0，危险！" if max(allr) >= 65536 else "否"))

    total_fail = 0

    print()
    print("=" * 72)
    print("PART B -- 真实轨迹（oracle 导出的 divvec）")
    print("=" * 72)
    dv = find_divvec(argv)
    if dv is None:
        print("跳过：找不到 divvec 文件（可用命令行第一个参数指定）")
        print("生成方式见 _logs\\sim\\gen_divvec.sh")
    else:
        print("向量文件 : %s" % dv)
        n = 0
        bad = []
        worst_gap = -1
        worst_case = None
        max_r0 = 0
        corr = 0
        max_xb = max_qb = 0
        inv_bad = 0
        xbins = {}
        for line in open(dv):
            p = line.split()
            if len(p) != 4:
                continue
            x, f = int(p[0], 16), int(p[1], 16)
            q, r = int(p[2], 16), int(p[3], 16)
            n += 1
            Q, R, q0, r0, c, wok = scheme(x, f)
            if (Q, R) != (q, r) or not wok:
                bad.append((hex(x), hex(f), hex(Q), hex(q)))
            gap = Q - q0
            if gap > worst_gap:
                worst_gap, worst_case = gap, (hex(x), hex(f))
            max_r0 = max(max_r0, r0)
            corr += c
            max_xb = max(max_xb, x.bit_length())
            max_qb = max(max_qb, q.bit_length())
            xbins[x.bit_length()] = xbins.get(x.bit_length(), 0) + 1
            # rANS 不变式：renorm 保证被除数 x < 2^47 * f
            if not (x < (1 << 47) * f):
                inv_bad += 1
        print("行数              : %d" % n)
        print("失配              : %d %s" % (len(bad), bad[:5]))
        print("max (Q - q0)      : %d   <-- 必须是 0 或 1，%s" % (worst_gap, worst_case))
        print("修正支路命中      : %d / %d = %.3f%%" % (corr, n, 100.0 * corr / n if n else 0))
        print("max (x - q0*f)    : %d   <-- 必须 < 2^17 = 131072" % max_r0)
        print("x 最大位宽        : %d ; q 最大位宽 : %d" % (max_xb, max_qb))
        print("不变式 x < 2^47*f 违反次数 : %d" % inv_bad)
        total_fail += len(bad)

    print()
    print("=" * 72)
    print("PART C -- 穷举 / 对抗 / 模糊")
    print("=" * 72)
    f1 = f2 = f3 = f4 = 0
    maxgap = 0

    # C1: 表里真实出现的每个 f，配各档极端被除数
    c1 = 0
    for f in sorted(set(allr)):
        for x in ((1 << 47) * f - 1, (1 << 47) * f - 2, 0, 1, 2,
                  (1 << 31) - 1, (1 << 31), (1 << 63), M64,
                  ((1 << 47) * f - 1) >> 1):
            if x < 0 or x >= (1 << 64):
                continue
            c1 += 1
            Q, R, q0, r0, c, wok = scheme(x, f)
            if (Q, R) != (x // f, x % f) or not wok:
                f1 += 1
            maxgap = max(maxgap, (x // f) - q0)
    print("C1 表内每个 f x 10 档极端值 (%d 例) : 失败 %d" % (c1, f1))

    # C2: 全部 f = 1..65535，配最坏被除数
    c2 = 0
    for f in range(1, 65536):
        for x in ((1 << 47) * f - 1, (1 << 63) - 1, M64):
            if x < 0 or x >= (1 << 64):
                continue
            c2 += 1
            Q, R, q0, r0, c, wok = scheme(x, f)
            if (Q, R) != (x // f, x % f) or not wok:
                f2 += 1
            maxgap = max(maxgap, (x // f) - q0)
    print("C2 全部 f=1..65535 x 3 档 (%d 例)   : 失败 %d" % (c2, f2))

    # C3: 随机模糊，三种取值域
    random.seed(20260914)
    for _ in range(300000):
        f = random.randint(1, 65535)
        mode = random.randint(0, 2)
        if mode == 0:
            x = random.randint(0, (1 << 47) * f - 1)
        elif mode == 1:
            x = random.randint(0, (1 << 63) - 1)
        else:
            x = random.getrandbits(64)
        if x >= (1 << 64):
            x = M64
        Q, R, q0, r0, c, wok = scheme(x, f)
        if (Q, R) != (x // f, x % f) or not wok:
            f3 += 1
        maxgap = max(maxgap, (x // f) - q0)
    print("C3 随机模糊 300000 例                : 失败 %d" % f3)

    # C4: 角点
    for f in (1, 2, 3, 65534, 65535):
        for x in (0, 1, 2, 3, M64 - 1, M64, (1 << 47) - 1, 1 << 47):
            Q, R, q0, r0, c, wok = scheme(x, f)
            if (Q, R) != (x // f, x % f) or not wok:
                f4 += 1
    print("C4 角点 (f=1/2/3/65534/65535)        : 失败 %d" % f4)

    print("全局 max (Q - q0)                    : %d" % maxgap)
    total_fail += f1 + f2 + f3 + f4

    print()
    print("=" * 72)
    print("结论：%s   （总失败 = %d）" % ("全过 PASS" if total_fail == 0 else "有失败 FAIL", total_fail))
    print("=" * 72)
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
