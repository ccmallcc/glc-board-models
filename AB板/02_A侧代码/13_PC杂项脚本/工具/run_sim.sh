#!/bin/bash
#======================================================================
# run_sim.sh -- 用 Icarus Verilog 编译并运行 E2 目录下所有 testbench
#----------------------------------------------------------------------
# 为什么要有它：
#   PL 侧时钟管脚在硬件手册里查不到 -> 位流出不来 -> **仿真是我们唯一能做的验证**。
#   而 2026-09-18 实测发现：AI（Qoder）写出来的「带自检的 testbench」**根本编译不过**
#   （$display 里用了 C 风格的多行字符串拼接，Verilog 不支持）。
#   所以「写了自检 tb」≠「tb 能跑」——**每次都必须真跑一遍**。
#
# 依赖：WSL Ubuntu-22.04 里的 iverilog 11.0（2026-09-18 装好）
#   安装命令：wsl -d Ubuntu-22.04 -u root -- bash -lc "apt-get install -y iverilog"
#
# 用法（Windows 侧）：
#   wsl -d Ubuntu-22.04 -- bash "/mnt/e/fudanwei/GLC-共享包/工具/run_sim.sh"
#
# 退出码：0=全过；2=有 FAIL；3=有编译失败
#======================================================================

set -u

SD=$(cd "$(dirname "$0")" && pwd)
# 可选第 1 个参数 = 工程目录（含 rtl/ 与 sim/）。不给就默认 E2 练习目录。
if [ $# -ge 1 ] && [ -n "$1" ]; then
    PROJ="$1"
else
    PROJ=$(ls -d "$SD"/../E2_FPGA* 2>/dev/null | head -1)
fi
if [ -z "$PROJ" ] || [ ! -d "$PROJ" ]; then
    echo "FATAL: 找不到工程目录（本脚本应在 工具/ 下，或显式传目录）"; exit 1
fi
echo "工程目录 : $PROJ"
cd "$PROJ" || exit 1

mkdir -p /tmp/e2sim
pass=0; fail=0; skip=0; cerr=0

for tb in sim/*_tb.v; do
    [ -e "$tb" ] || { echo "FATAL: sim/ 下没有 *_tb.v"; exit 1; }
    base=$(basename "$tb" _tb.v)

    echo ""
    echo "=============================================================="
    echo "=== $base"
    echo "=============================================================="

    if [ ! -f "rtl/$base.v" ]; then
        echo ">>> SKIP：rtl/$base.v 不存在"
        skip=$((skip+1)); continue
    fi

    # 编译 **全部** rtl/*.v + 本 tb —— 这才是真实工程的样子（Procise 也是把
    # 所有源文件一起 elaborate）。以前只编 rtl/<同名>.v，导致含子模块的设计
    # 编不过，逼得 Qoder 在 led_modes.v 里写 `include "rtl/debounce.v"` 绕过；
    # 那种写法在 Procise 里会变成重复模块定义。2026-09-18 改。
    if ! iverilog -g2001 -Wall -o "/tmp/e2sim/$base.vvp" rtl/*.v "$tb" 2>&1; then
        echo ">>> 编译失败"
        cerr=$((cerr+1)); continue
    fi

    out=$(cd /tmp/e2sim && vvp "$base.vvp" 2>&1)
    echo "$out" | tail -30

    if echo "$out" | grep -qiE '\bFAIL|ERROR|Fatal'; then
        echo ">>> 判定：FAIL"
        fail=$((fail+1))
    elif echo "$out" | grep -qiE '\bPASS'; then
        echo ">>> 判定：PASS"
        pass=$((pass+1))
    else
        echo ">>> 判定：不明确（没打印 PASS/FAIL）<- testbench 没有自检"
        skip=$((skip+1))
    fi
done

echo ""
echo "=============================================================="
echo "汇总：PASS=$pass  FAIL=$fail  编译失败=$cerr  跳过/无自检=$skip"
echo "=============================================================="
[ "$fail" -eq 0 ] || exit 2
[ "$cerr" -eq 0 ] || exit 3
