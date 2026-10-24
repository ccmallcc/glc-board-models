#!/bin/bash
# V5 step 2-3: build a container on the board path and compare it byte-for-byte
# with the container the team's own codec produced from the same operands.
R=/mnt/e/fudanwei/工作区/rans
V=/mnt/e/fudanwei/工作区/v5
fail=0
for i in 0 1 2 3; do
  echo "########## img$i ##########"
  if ! "$R/glc2_pack" "$V/img$i" "$V/img$i/board.glc"; then fail=1; fi
  if cmp -s "$V/img$i/board.glc" "$V/img$i/ref.glc"; then
    echo "  与团队参考容器逐字节比较 : 完全一致 ✅  ($(stat -c%s "$V/img$i/board.glc") B)"
  else
    echo "  与团队参考容器逐字节比较 : 不一致 ❌"
    cmp "$V/img$i/board.glc" "$V/img$i/ref.glc" | head -3
    fail=1
  fi
  md5sum "$V/img$i/board.glc" | sed 's/^/  md5(board) = /'
  md5sum "$V/img$i/ref.glc"   | sed 's/^/  md5(ref)   = /'
  echo
done
echo "=================================================="
[ $fail -eq 0 ] && echo "自产容器：全部与团队参考逐字节一致 ✅" || echo "存在不一致 ❌"
exit $fail
