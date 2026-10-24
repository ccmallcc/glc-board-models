#!/bin/bash
# C2d 仿真：重新生成向量 + 编译 + 跑 testbench
set -u
REPO=/mnt/e/fudanwei/GLC-共享包
C2=$REPO/C2_PL熵编码器
cd "$C2" || exit 1

echo "########## 1. 重新生成向量（顺序已修正：_rans.txt 按 reverse(seq)）##########"
bash /mnt/e/fudanwei/_logs/sim/c2d_vectors.sh 2>&1 | grep -E "^  ✅|^  ❌|自检|官方 encode|压力向量|找不到" | sed 's/^/  /'

echo
echo "########## 2. 编译 testbench ##########"
iverilog -g2012 -o /tmp/c2d_sim rtl/rans_cdf.v sim/rans_cdf_tb.v 2>&1 | head -20
[ -f /tmp/c2d_sim ] && echo "  ✅ 编译通过" || { echo "  ❌ 编译失败"; exit 1; }

echo
echo "########## 3. 跑真实数据向量（无 escape）##########"
vvp /tmp/c2d_sim +VEC=sim/vec/real 2>&1 | sed 's/^/  /'

echo
echo "########## 4. 跑 escape 压力向量 ##########"
vvp /tmp/c2d_sim +VEC=sim/vec/stress 2>&1 | sed 's/^/  /'
