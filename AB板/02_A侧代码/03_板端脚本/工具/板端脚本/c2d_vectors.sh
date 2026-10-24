#!/bin/bash
# 编译并生成 C2d 的两套向量：真实数据 + escape 压力
set -u
REPO=/mnt/e/fudanwei/GLC-共享包
HDR=$REPO/assets/板端代码
SIM=$REPO/C2_PL熵编码器/sim
OPS=${1:-/mnt/e/fudanwei/工作区/_board_run/e2e4/operands/img0}
OUT=$SIM/vec
mkdir -p "$OUT"

echo "########## 编译 ##########"
for t in gen_c2d_vector gen_c2d_stress; do
  g++ -O2 -std=c++11 -I"$HDR" -o "$SIM/$t" "$SIM/$t.cpp" 2>&1 | head -10
  [ -x "$SIM/$t" ] && echo "  ✅ $t" || { echo "  ❌ $t 编译失败"; exit 1; }
done

echo
echo "########## A. 真实数据向量（phase 0，无 escape）##########"
"$SIM/gen_c2d_vector" "$OPS/p0_sym.i32" "$OPS/p0_scales.f32" "$OUT/real"
[ $? -eq 0 ] || { echo "  ❌ 失败"; exit 1; }

echo
echo "########## B. escape 压力向量 ##########"
"$SIM/gen_c2d_stress" "$OUT/stress_sym.i32" "$OUT/stress_scales.f32" || exit 1
echo
"$SIM/gen_c2d_vector" "$OUT/stress_sym.i32" "$OUT/stress_scales.f32" "$OUT/stress" || exit 1

echo
echo "########## 向量一览 ##########"
ls -l "$OUT" | sed 's/^/  /'
echo
for v in real stress; do
  echo "--- $v stats ---"
  cat "$OUT/${v}_stats.txt" | sed 's/^/  /'
done
