#!/bin/bash
# 决定性实验：给不同的 STAGE_LEN 初值，看 glc2_pack 报什么
# 操作数就用当前 full_img0 里的（p7 的）
cd /root/glc/pack || exit 1
D=full_img0
cp $D/hdr.txt /tmp/hdr.save
for V in 4096 512 128 100 60 56 52 48 0; do
  sed -i "s/^STAGE\([0-3]\)_LEN .*/STAGE\1_LEN $V/" $D/hdr.txt
  echo "----- 初值 STAGE*_LEN = $V -----"
  ./glc2_pack $D /tmp/tv.glc 2>&1 | grep -E 'phase [0-3]:|自产容器' | sed 's/^/    /'
  if [ -f /tmp/tv.glc ]; then
    echo -n "    容器 $(stat -c%s /tmp/tv.glc) B  头长度="
    od -An -tu4 --endian=big -j56 -N16 /tmp/tv.glc | tr -s ' '
  fi
  rm -f /tmp/tv.glc
done
cp /tmp/hdr.save $D/hdr.txt
echo "  (hdr.txt 已还原)"
echo SWEEP_DONE
