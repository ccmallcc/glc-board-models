#!/bin/bash
# 编译 gen_c2d_vector 并为零/若干 phase 生成黄金向量
set -u
REPO=/mnt/e/fudanwei/GLC-共享包
HDR=$REPO/assets/板端代码
SIM=$REPO/C2_PL熵编码器/sim
OPS=${1:-/mnt/e/fudanwei/工作区/_board_run/e2e4/operands/img0}
PH=${2:-0}
OUT=$SIM/vec
mkdir -p "$OUT"

echo "=== 编译 ==="
g++ -O2 -std=c++11 -I"$HDR" -o "$SIM/gen_c2d_vector" "$SIM/gen_c2d_vector.cpp" 2>&1 | head -20
[ -x "$SIM/gen_c2d_vector" ] && echo "  ✅ 编译通过" || { echo "  ❌ 编译失败"; exit 1; }

echo
echo "=== 输入核对 ==="
for f in "$OPS/p${PH}_sym.i32" "$OPS/p${PH}_scales.f32"; do
  [ -f "$f" ] && echo "  ✅ $(basename $f)  $(stat -c%s $f) B" || { echo "  ❌ 缺 $f"; exit 1; }
done

echo
echo "=== 生成黄金向量（phase $PH）==="
"$SIM/gen_c2d_vector" "$OPS/p${PH}_sym.i32" "$OPS/p${PH}_scales.f32" "$OUT/p${PH}"
RC=$?
echo "  rc=$RC"
echo
echo "=== 产出 ==="
ls -l "$OUT" | sed 's/^/  /'
echo
echo "=== stats ==="
cat "$OUT/p${PH}_stats.txt" 2>/dev/null | sed 's/^/  /'
echo
echo "=== rANS 符号流前 8 行 / 后 4 行（start range bypass last）==="
head -8 "$OUT/p${PH}_rans.txt" | sed 's/^/  /'
echo "  ..."
tail -4 "$OUT/p${PH}_rans.txt" | sed 's/^/  /'
echo
echo "=== 逻辑符号流前 5 行（k value）==="
head -5 "$OUT/p${PH}_logical.txt" | sed 's/^/  /'
