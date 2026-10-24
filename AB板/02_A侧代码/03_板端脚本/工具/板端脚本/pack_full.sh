#!/bin/sh
# pack_full.sh <i> —— 用 A53 CPU 的 glc2_pack 在**板端自产操作数** full_img<i> 上产容器，
# 并与 PL 的容器、以及 PC 链路的 img<i>.glc 三方对拍。
set -u
cd /root/glc/pack || exit 1
i=$1
D=full_img$i

if [ ! -f "$D/hdr.txt" ]; then
  cp /root/glc/ref_stage/pack_img$i/hdr.txt "$D/hdr.txt"
  for k in 0 1 2 3; do
    sed -i "s/^STAGE${k}_LEN .*/STAGE${k}_LEN 0/" "$D/hdr.txt"
  done
fi

for k in 0 1 2 3; do
  ./glc2_pack "$D" /tmp/_o.glc > /tmp/_p.txt 2>&1
  n=$(grep -E "^  phase $k:" /tmp/_p.txt | grep -oE '\-> +[0-9]+ B' | grep -oE '[0-9]+')
  if [ -z "$n" ]; then echo "  phase$k 解析失败"; exit 1; fi
  sed -i "s/^STAGE${k}_LEN .*/STAGE${k}_LEN $n/" "$D/hdr.txt"
done
S=$(date +%s%N)
./glc2_pack "$D" /root/glc/pack/full_img${i}_cpu.glc > /tmp/_f.txt 2>&1
E=$(date +%s%N)
echo "  A53 CPU glc2_pack : $(grep -oE '自产容器 [0-9]+ B' /tmp/_f.txt | head -1)  用时 $(( (E-S)/1000000 )) ms"

if cmp -s /root/glc/pack/full_img${i}_cpu.glc /root/glc/pack/full_img$i.glc; then
  echo "  ==> PL rANS == A53 CPU rANS  **逐字节一致**"
else
  echo "  ==> PL 与 A53 CPU **不一致**"
  cmp -l /root/glc/pack/full_img${i}_cpu.glc /root/glc/pack/full_img$i.glc | head -5
fi

if [ -f /root/glc/pack/img$i.glc ]; then
  if cmp -s /root/glc/pack/full_img$i.glc /root/glc/pack/img$i.glc; then
    echo "  ==> 板端全链路 == PC 链路(img$i.glc)  **逐字节一致**"
  else
    echo "  ==> 板端全链路与 PC 链路 **不一致**"
    cmp -l /root/glc/pack/full_img$i.glc /root/glc/pack/img$i.glc | head -5
  fi
fi
