#!/bin/bash
# C2d 完整验收：向量生成 + 展开层 tb + 联调 payload 对拍
set -u
REPO=/mnt/e/fudanwei/GLC-共享包
C2=$REPO/C2_PL熵编码器
cd "$C2" || exit 1
FAIL=0

echo "########## 1. 生成向量（生成器自带自检）##########"
bash /mnt/e/fudanwei/_logs/sim/c2d_vectors.sh 2>&1 \
  | grep -E "自检|官方 encode|压力向量|找不到|❌" | sed 's/^/  /'

echo
echo "########## 2. 编译（展开层 + 联调）##########"
iverilog -g2012 -o /tmp/c2d_exp   rtl/rans_cdf.v sim/rans_cdf_tb.v 2>&1 | head -10
[ -f /tmp/c2d_exp ] && echo "  ✅ 展开层 tb 编译通过" || { echo "  ❌ 展开层编译失败"; exit 1; }
iverilog -g2012 -o /tmp/c2d_chain rtl/rans_cdf.v rtl/rans_enc_put.v rtl/rans_enc_stream.v sim/rans_chain_tb.v 2>&1 | head -10
[ -f /tmp/c2d_chain ] && echo "  ✅ 联调 tb 编译通过" || { echo "  ❌ 联调编译失败"; exit 1; }

for v in real stress; do
  echo
  echo "########## 向量 $v ##########"
  echo "--- A. 展开层（逐 rANS 符号）---"
  vvp /tmp/c2d_exp +VEC=sim/vec/$v 2>&1 | grep -E "向量|发射数量|DUT 统计|结论" | sed 's/^/  /'
  echo "--- B. 联调（payload 逐字）---"
  vvp /tmp/c2d_chain +VEC=sim/vec/$v 2>&1 | grep -E "向量|payload|字\[|C2d 统计|结论" | sed 's/^/  /'
done

echo
echo "########## 产出 ##########"
ls -l sim/vec | sed 's/^/  /'
