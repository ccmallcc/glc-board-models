#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
xref_board_pins.py —— 用 Xilinx 官方封装文件**交叉验证**硬件手册里已公布的管脚。

为什么值得做：如果逐条都对上，就证明
  ① jfmql30tai 的封装管脚与 xc7z030ffg676 **引脚兼容**；
  ② 我们手里这份公开文件**可以当这块板的器件侧参考**；
  ③ 进而可以用它来**筛选 PL 时钟候选脚**。
"""
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "/mnt/e/fudanwei/_logs/pdf/xc7z030ffg676pkg.txt"

pkg = {}
for line in open(SRC, encoding="utf-8", errors="replace"):
    p = line.split()
    if len(p) < 7 or p[0] == "Pin" or line.startswith("Device/Package"):
        continue
    pkg[p[0]] = (p[1], p[3])

# 全部来自《悟净开发板硬件使用手册V1.0_嵌赛》：4.12 LED / 4.13 按键 / 4.8 千兆网
KNOWN = [
    ("PL_LED1",  "J1",   None),
    ("PL_LED2",  "M6",   None),
    ("PL_LED3",  "H7",   None),
    ("PL_LED4",  "J8",   None),
    ("PL_KEY1",  "F8",   "IO_L11P_T1_SRCC_34"),
    ("PL_KEY2",  "E7",   "IO_L11N_T1_SRCC_34"),
    ("PL_PHY_TX_CLK",  "AD23", None),
    ("PL_PHY_TX_CTRL", "AD26", None),
    ("PL_PHY_TXD0",    "AF24", None),
    ("PL_PHY_TXD1",    "AF25", None),
    ("PL_PHY_TXD2",    "AA24", None),
    ("PL_PHY_TXD3",    "AB24", None),
    ("PL_PHY_RX_CLK",  "AC23", None),
    ("PL_PHY_RX_CTRL", "AA25", None),
    ("PL_PHY_RXD0",    "AB26", None),
    ("PL_PHY_RXD1",    "AC26", None),
    ("PL_PHY_RXD2",    "AE25", None),
    ("PL_PHY_RXD3",    "AE26", None),
    ("PL_PHY_MDC",     "AE22", None),
    ("PL_PHY_MDIO",    "AF22", None),
    ("PL_PHY_RESET",   "AA13", None),
]

print("=" * 92)
print("硬件手册已公布管脚  vs  Xilinx 官方封装文件 xc7z030ffg676pkg.txt")
print("=" * 92)
print("%-16s %-5s %-34s %-8s %s" % ("信号", "脚", "官方文件里的管脚名", "Bank", "手册写的一致?"))
print("-" * 92)
ok = mismatch = 0
banks = {}
for sig, pin, manual_name in KNOWN:
    got = pkg.get(pin)
    if not got:
        print("%-16s %-5s %s" % (sig, pin, "**文件里没有这个脚**"))
        mismatch += 1
        continue
    name, bank = got
    banks[bank] = banks.get(bank, 0) + 1
    if manual_name:
        good = (name == manual_name)
        ok += good
        mismatch += (not good)
        print("%-16s %-5s %-34s %-8s %s" % (sig, pin, name, bank, "✅ 一致" if good else "❌ 手册写的是 " + manual_name))
    else:
        print("%-16s %-5s %-34s %-8s %s" % (sig, pin, name, bank, "（手册没给脚名，无法比对）"))

print("-" * 92)
print("手册给了脚名的比对结果：一致 %d 条，不一致 %d 条" % (ok, mismatch))
print("这些管脚分布在 Bank：%s" % ", ".join(sorted(banks)))
