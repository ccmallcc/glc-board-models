#!/bin/bash
# C2e 端到端验收：寄存器接口 + PL DDR + rANS 全路径
set -u
REPO=/mnt/e/fudanwei/GLC-共享包
C2=$REPO/C2_PL熵编码器
cd "$C2" || exit 1

echo "########## 编译 ##########"
iverilog -g2012 -o /tmp/c2e \
  rtl/rans_top.v rtl/rans_cdf.v rtl/rans_enc_stream.v rtl/rans_enc_put.v \
  rtl/official/reg_ctrl.v rtl/official/pulse_cross.v \
  sim/rans_top_tb.v 2>&1 | head -25
[ -f /tmp/c2e ] && echo "  ✅ 编译通过" || { echo "  ❌ 编译失败"; exit 1; }

for v in real stress; do
  echo
  echo "########## 向量 $v ##########"
  timeout 300 vvp /tmp/c2e +VEC=sim/vec/$v 2>&1 | sed 's/^/  /'
done
