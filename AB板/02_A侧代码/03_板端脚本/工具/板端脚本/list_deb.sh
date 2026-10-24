#!/bin/bash
# 列出板端 runtime deb 的文件清单，回答「板子本地能不能跑 icraft-run / ZG330 本地设备」
SRC="/mnt/e/fudanwei/官方资料/2026嵌赛/04_ICraft/v3.36.1/ICraft_V3.36.1安装包"
TMP=/tmp/icraft_deb
rm -rf "$TMP"; mkdir -p "$TMP"
cp "$SRC/Icraft_3.36.1_onchip.deb"    "$TMP/A.deb"
cp "$SRC/CustomOp_3.36.1_onchip.deb"   "$TMP/B.deb"

for f in A B; do
  echo "===================== $f.deb 文件清单 ====================="
  dpkg-deb -c "$TMP/$f.deb" 2>/dev/null | sed 's/^.*[0-9]  //' | sed 's|^\./||' | sort
  echo
  echo "----- 包信息 -----"
  dpkg-deb -f "$TMP/$f.deb" 2>/dev/null
  echo
done
