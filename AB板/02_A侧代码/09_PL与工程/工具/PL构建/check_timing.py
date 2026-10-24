#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""check_timing.py —— 把新版本的时序摘要与基线逐项对比（2026-10-14）

用途：Vivado 构建完成后，**自动判定"不劣于基线"**，不用人眼去 5 MB 的报告里找数字。

基线（各版本实测，取自 rans_board/timing_rans_v*.rpt）：

  版本   WNS      TNS        TNS失败   WHS      THS失败   WPWS     TPWS失败
  v6    +0.030    0.000         0     +0.029      0     -0.409       2
  v7    -5.284  -553.754     1229     +0.029      0     -0.409       2     (作废)
  v8    +0.010    0.000         0     +0.029      0     -0.409       2     (现行)
  v9    ?                                                                  (本次)

判据（V9 相对 V8）：
  · WNS  >= 0（必须无建立失败）
  · TNS 失败端点 == 0
  · WHS  >  0 且 THS 失败端点 == 0
  · TPWS 失败端点 == 2（那 2 个在官方 IP 的 1000MHz 时钟上，v4~v8 五个版本数字完全一样，
    是**官方自带、改不动**，不是我们引入的）

用法：
    python check_timing.py <timing_rans_vX.rpt> [基线版本=V8]
"""
import re
import sys

BASE = {
    "v4": dict(wns=-0.317, tns=None, tns_fail=None, whs=None, ths_fail=None, wpws=None, tpws_fail=None),
    "v5": dict(wns=-0.119, tns=None, tns_fail=None, whs=None, ths_fail=None, wpws=None, tpws_fail=None),
    "v6": dict(wns=+0.030, tns=0.000, tns_fail=0, whs=+0.029, ths_fail=0, wpws=-0.409, tpws_fail=2),
    "v7": dict(wns=-5.284, tns=-553.754, tns_fail=1229, whs=+0.029, ths_fail=0, wpws=-0.409, tpws_fail=2),
    "v8": dict(wns=+0.010, tns=0.000, tns_fail=0, whs=+0.029, ths_fail=0, wpws=-0.409, tpws_fail=2),
}


def parse(path):
    txt = open(path, encoding="utf-8", errors="replace").read()
    # Design Timing Summary 表：WNS TNS TNS失败 总数 WHS THS THS失败 总数 WPWS TPWS TPWS失败 总数
    pat = re.compile(
        r"(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(\d+)\s+(\d+)\s+"
        r"(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(\d+)\s+(\d+)\s+"
        r"(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(\d+)\s+(\d+)")
    m = pat.search(txt)
    if not m:
        raise SystemExit("在 %s 里找不到 Design Timing Summary 的 12 个数字" % path)
    g = m.groups()
    return dict(wns=float(g[0]), tns=float(g[1]), tns_fail=int(g[2]), tns_total=int(g[3]),
                whs=float(g[4]), ths=float(g[5]), ths_fail=int(g[6]), ths_total=int(g[7]),
                wpws=float(g[8]), tpws=float(g[9]), tpws_fail=int(g[10]), tpws_total=int(g[11]))


def main():
    path = sys.argv[1]
    base_ver = (sys.argv[2] if len(sys.argv) > 2 else "v8").lower()
    b = BASE.get(base_ver)
    if b is None:
        raise SystemExit("未知基线版本 %r，可选 %s" % (base_ver, sorted(BASE)))
    r = parse(path)

    print("=" * 78)
    print("  时序核对：%s" % path)
    print("  基线 = %s" % base_ver.upper())
    print("=" * 78)
    print("  %-22s %14s %14s   %s" % ("指标", "基线 " + base_ver.upper(), "本次", "判定"))
    print("  " + "-" * 74)

    ok = True

    def row(name, cur, ref, good, fmt="%.3f"):
        nonlocal ok
        mark = "OK" if good else "**不达标**"
        if not good:
            ok = False
        refs = (fmt % ref) if isinstance(ref, float) else str(ref)
        print("  %-22s %14s %14s   %s" % (name, refs, fmt % cur, mark))

    row("WNS (建立裕量 ns)", r["wns"], b["wns"], r["wns"] >= 0)
    row("TNS (总建立违例 ns)", r["tns"], b["tns"], abs(r["tns"]) < 1e-9)
    row("TNS 失败端点数", float(r["tns_fail"]), float(b["tns_fail"]), r["tns_fail"] == 0, "%.0f")
    row("WHS (保持裕量 ns)", r["whs"], b["whs"], r["whs"] > 0)
    row("THS 失败端点数", float(r["ths_fail"]), float(b["ths_fail"]), r["ths_fail"] == 0, "%.0f")
    row("WPWS (脉宽裕量 ns)", r["wpws"], b["wpws"], True)          # 官方 IP 自带，只记录不判
    row("TPWS 失败端点数", float(r["tpws_fail"]), float(b["tpws_fail"]), r["tpws_fail"] <= 2, "%.0f")

    print("  " + "-" * 74)
    print("  端点总数: 建立 %d / 保持 %d / 脉宽 %d" % (r["tns_total"], r["ths_total"], r["tpws_total"]))
    if r["tpws_fail"] == 2:
        print("  ★ 那 2 个 TPWS 失败在官方 IP 的 1000MHz 时钟上，v4~v8 五个版本完全一样，")
        print("    是官方自带、改不动的，不算我们引入的。")
    print()
    print("  ⇒ 结论：%s" % ("**不劣于基线，通过**" if ok else "**未达标，需要看 worst_max 报告**"))
    print("CHECK_DONE")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
