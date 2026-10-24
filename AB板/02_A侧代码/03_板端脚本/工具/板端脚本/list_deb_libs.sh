#!/bin/bash
# 只看库和可执行文件：板端本地能不能跑 NPU？
SRC="/mnt/e/fudanwei/官方资料/2026嵌赛/04_ICraft/v3.36.1/ICraft_V3.36.1安装包"
TMP=/tmp/icraft_deb
rm -rf "$TMP"; mkdir -p "$TMP"
cp "$SRC/Icraft_3.36.1_onchip.deb"  "$TMP/A.deb"
cp "$SRC/CustomOp_3.36.1_onchip.deb" "$TMP/B.deb"

for f in A B; do
  echo "===================== $f.deb ====================="
  dpkg-deb -c "$TMP/$f.deb" 2>/dev/null | grep -E '\.so|/bin/|\.a$|\.bin$' | sed 's/^.*[0-9]  //' | sort
  echo
done

echo "===================== 两个包合起来的 usr/bin ====================="
for f in A B; do dpkg-deb -c "$TMP/$f.deb" 2>/dev/null; done | grep -E 'usr/bin/' | sed 's/^.*[0-9]  //' | sort -u
