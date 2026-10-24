#!/bin/bash
# C2e 前置：直接证明官方 reg_ctrl.v 的 RFU_W3/W4 是 1 位寄存器
set -u
C2=/mnt/e/fudanwei/GLC-共享包/C2_PL熵编码器
cd "$C2" || exit 1
rm -f /tmp/quirk
iverilog -g2012 -o /tmp/quirk rtl/official/reg_ctrl.v sim/reg_ctrl_quirk_tb.v 2>&1 | head -30
[ -f /tmp/quirk ] || { echo "COMPILE FAIL"; exit 1; }
vvp /tmp/quirk
