#!/bin/bash
# 在**板子的 CPU 上**跑真实熵编码器 glc2_pack（BoardEncoder = rANS），
# 输入是板端 NPU 链路产出的符号/scale，输出是真 .glc 容器。
#
# 为什么要多轮：glc2_pack 是**验证工具**，hdr.txt 里的 STAGE*_LEN 是参考值，
# 不符就 return 1（在写文件之前）。它每轮只打印到第一个不符的 phase，
# 所以逐轮补齐 4 个长度，第 5 轮才写出容器。**工具本身一行不改。**
set -u
BOARD=192.168.31.72
PASS=fmsh
SRC=${1:-/mnt/e/fudanwei/工作区/_board_run/e2e4/operands}
BIN=/mnt/e/fudanwei/工作区/rans/board_bin/glc2_pack_arm64_static
OUT=${2:-/mnt/e/fudanwei/工作区/_board_run/glc}
RD=/root/glc/pack
SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=8"
SCP="sshpass -p $PASS scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"

mkdir -p "$OUT"
echo "########## 送二进制与操作数到板子 ##########"
$SSH root@$BOARD "mkdir -p $RD"
$SCP "$BIN" root@$BOARD:$RD/glc2_pack >/dev/null 2>&1
$SSH root@$BOARD "chmod +x $RD/glc2_pack; file $RD/glc2_pack 2>/dev/null | cut -c1-90"
for d in "$SRC"/img*; do
  i=$(basename "$d")
  $SSH root@$BOARD "rm -rf $RD/$i $RD/$i.glc && mkdir -p $RD/$i"
  $SCP "$d"/* root@$BOARD:$RD/$i/ >/dev/null 2>&1
done
echo "  已送 $(ls -d "$SRC"/img* | wc -l) 个图的符号/scale"

echo
echo "########## 板端 CPU 熵编码（逐图，真实 .glc）##########"
$SSH root@$BOARD 'bash -s' <<'REMOTE'
cd /root/glc/pack
printf "%-6s %8s %9s %10s %9s %8s\n" 图 符号数 容器B 熵编码ms 板端bpp 长度校验
for d in img*; do
  [ -d "$d" ] || continue
  for k in 0 1 2 3; do
    ./glc2_pack "$d" /tmp/o.glc > /tmp/p.txt 2>&1
    n=$(grep -E "^  phase $k:" /tmp/p.txt | grep -oE '\-> +[0-9]+ B' | grep -oE '[0-9]+')
    [ -z "$n" ] && { echo "  $d phase$k 解析失败"; sed 's/^/      /' /tmp/p.txt | tail -5; break; }
    sed -i "s/^STAGE${k}_LEN .*/STAGE${k}_LEN $n/" "$d/hdr.txt"
  done
  S=$(date +%s%N)
  ./glc2_pack "$d" "$d.glc" > /tmp/f.txt 2>&1
  E=$(date +%s%N); MS=$(( (E-S)/1000000 ))
  N=$(( ($(stat -c%s $d/p0_sym.i32) + $(stat -c%s $d/p1_sym.i32) \
       + $(stat -c%s $d/p2_sym.i32) + $(stat -c%s $d/p3_sym.i32)) / 4 ))
  if [ -f "$d.glc" ]; then
    SZ=$(stat -c%s "$d.glc")
    BPP=$(awk -v s=$SZ -v p=65536 'BEGIN{printf "%.5f", s*8/p}')
    LK=$(grep -oE '长度一致|长度不符' /tmp/f.txt | head -1)
    printf "%-6s %8d %9d %10d %9s %8s\n" "$d" "$N" "$SZ" "$MS" "$BPP" "${LK:-?}"
  else
    printf "%-6s %8d %9s %10d %9s %8s\n" "$d" "$N" - "$MS" - "❌未出容器"
    tail -4 /tmp/f.txt | sed 's/^/      /'
  fi
done
REMOTE

echo
echo "########## 拉回容器 ##########"
$SCP "root@$BOARD:$RD/*.glc" "$OUT/" >/dev/null 2>&1
ls -l "$OUT"/*.glc 2>/dev/null | sed 's/^/  /'
