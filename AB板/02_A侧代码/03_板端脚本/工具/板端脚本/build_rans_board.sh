#!/bin/bash
# 交叉编译板端 PL rANS 驱动程序（aarch64 静态）
set -u
REPO=/mnt/e/fudanwei/GLC-共享包
SRC="$REPO/工具/板端程序"
OUT=/mnt/e/fudanwei/_logs/sim/rb
mkdir -p "$OUT"

echo "########## 编译 ##########"
aarch64-linux-gnu-g++ -O2 -std=c++17 -static -Wall \
  -I"$REPO/assets/板端代码" \
  -o "$OUT/rans_board" "$SRC/rans_board.cpp" 2>&1 | head -60

if [ -f "$OUT/rans_board" ]; then
  echo "  OK: $OUT/rans_board  ($(stat -c%s "$OUT/rans_board") 字节)"
  aarch64-linux-gnu-readelf -h "$OUT/rans_board" | grep -E 'Machine|Class|Type'
else
  echo "  编译失败"
  exit 1
fi
