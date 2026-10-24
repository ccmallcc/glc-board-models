#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""列出 PL 侧各 Bank 里**可作时钟输入**的脚（MRCC/SRCC），并标出已被已知信号占用的那些。"""
import re
import sys

SRC = "/mnt/e/fudanwei/GLC-共享包/assets/官方文档摘录/xc7z030ffg676_官方封装管脚表.txt"

rows = []
for line in open(SRC, encoding="utf-8", errors="replace"):
    p = line.split()
    if len(p) < 7 or p[0] == "Pin" or line.startswith("Device/Package"):
        continue
    m = re.search(r"_(\d+)$", p[1])
    if not m:
        continue
    rows.append((p[0], p[1], int(m.group(1))))

# 已知板级占用（来自硬件手册）
KNOWN = {
    "J1": "PL_LED1", "M6": "PL_LED2", "H7": "PL_LED3", "J8": "PL_LED4",
    "F8": "PL_KEY1", "E7": "PL_KEY2",
    "AD23": "PL_PHY_TX_CLK", "AD26": "PL_PHY_TX_CTRL", "AF24": "PL_PHY_TXD0",
    "AF25": "PL_PHY_TXD1", "AA24": "PL_PHY_TXD2", "AB24": "PL_PHY_TXD3",
    "AC23": "PL_PHY_RX_CLK", "AA25": "PL_PHY_RX_CTRL", "AB26": "PL_PHY_RXD0",
    "AC26": "PL_PHY_RXD1", "AE25": "PL_PHY_RXD2", "AE26": "PL_PHY_RXD3",
    "AE22": "PL_PHY_MDC", "AF22": "PL_PHY_MDIO", "AA13": "PL_PHY_RESET",
}

PL_BANKS = [12, 13, 33, 34, 35]
print("=" * 96)
print("xc7z030ffg676 —— PL 侧 Bank 里**可作时钟输入**的脚（MRCC/SRCC）")
print("=" * 96)
free, used = [], []
for b in PL_BANKS:
    lst = sorted([r for r in rows if r[2] == b and ("_MRCC_" in r[1] or "_SRCC_" in r[1])],
                 key=lambda r: r[0])
    if not lst:
        print("Bank %-3d : （没有 MRCC/SRCC 脚）" % b)
        continue
    print("Bank %-3d :" % b)
    for pin, name, _ in lst:
        tag = KNOWN.get(pin)
        mark = ("← 已占用：%s" % tag) if tag else "★ 候选"
        (used if tag else free).append((pin, name, b))
        print("    %-5s %-34s %s" % (pin, name, mark))
print("-" * 96)
print("可作 PL 时钟输入的总数 : %d" % (len(free) + len(used)))
print("  已被已知信号占用     : %d" % len(used))
print("  ★ 仍**空着**的候选     : %d  ->  %s"
      % (len(free), "  ".join("%s(%s,B%d)" % (p, n.split('_')[0] + '_' + n.split('_')[1], b) for p, n, b in free)))
