#!/bin/bash
# V5 extra: same closed loop at a second resolution (640x800 whole images).
R=/mnt/e/fudanwei/工作区/rans
V="${1:-/mnt/e/fudanwei/工作区/v5_full}"
N="${2:-2}"
fail=0
for i in $(seq 0 $((N - 1))); do
  [ -d "$V/img$i" ] || continue
  echo "########## $(basename $V)/img$i ##########"
  "$R/glc2_pack" "$V/img$i" "$V/img$i/board.glc" | grep -E '参考容器|phase|z:|自产容器'
  if cmp -s "$V/img$i/board.glc" "$V/img$i/ref.glc"; then
    echo "  逐字节 vs 参考容器 : 完全一致 ✅ ($(stat -c%s "$V/img$i/board.glc") B  md5=$(md5sum "$V/img$i/board.glc" | cut -c1-12))"
  else
    echo "  逐字节 vs 参考容器 : 不一致 ❌"; fail=1
  fi
  echo
done
echo "=================================================="
[ $fail -eq 0 ] && echo "第二分辨率：自产容器全部与参考逐字节一致 ✅" || echo "存在不一致 ❌"
exit $fail
