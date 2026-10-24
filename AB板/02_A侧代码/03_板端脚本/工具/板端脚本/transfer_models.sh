#!/bin/bash
# 把 5 个子图的 _ZG 产物全部传到板子（真·千兆直连），量速率 + md5 校验
set -u
BOARD=192.168.31.72
PASS=fmsh
ROOT=/mnt/e/fudanwei/工作区/compile_real
DST=/root/glc/models
SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=8"
SCP="sshpass -p $PASS scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"

SUB="s1:encoder_ga_hyper s2:hyperdec_fusion s3p1:phase1 s3p2:phase2 s3p3:phase3"

echo "########## 暂存到本地（WSL）##########"
STAGE=/tmp/glc_models
rm -rf $STAGE; mkdir -p $STAGE
TOT=0
for pair in $SUB; do
  d=${pair%%:*}; n=${pair##*:}
  src=$ROOT/${d}_int8/gen
  for ext in json raw; do
    f=$(ls $src/*_ZG.$ext 2>/dev/null | head -1)
    [ -z "$f" ] && { echo "  ❌ 缺 $d $ext"; continue; }
    cp "$f" $STAGE/ || exit 1
    sz=$(stat -c%s "$f"); TOT=$((TOT+sz))
    printf "  %-22s %12d B\n" "$(basename $f)" "$sz"
  done
done
echo "  ------------------------------"
printf "  合计 %d 字节 = %.1f MB\n" "$TOT" "$(echo "$TOT/1048576" | awk '{printf "%.1f",$1}')"

echo
echo "########## 建板端目录 ##########"
$SSH root@$BOARD "mkdir -p $DST && df -h / | tail -1"

echo
echo "########## 传输（计时）##########"
S=$(date +%s%N)
if ! $SCP $STAGE/* root@$BOARD:$DST/ 2>&1 | tail -3; then echo "  ❌ scp 失败"; exit 1; fi
E=$(date +%s%N)
MS=$(( (E-S)/1000000 ))
awk -v t=$TOT -v m=$MS 'BEGIN{ s=m/1000; printf "  耗时 %.1f s  ->  %.2f MB/s (%.1f Mbit/s)\n", s, t/1048576/s, t*8/1000000/s }'

echo
echo "########## md5 逐文件校验 ##########"
BAD=0
for f in $STAGE/*; do
  b=$(basename "$f")
  L=$(md5sum "$f" | cut -d' ' -f1)
  R=$($SSH root@$BOARD "md5sum $DST/$b 2>/dev/null | cut -d' ' -f1")
  if [ "$L" = "$R" ]; then printf "  ✅ %-28s %s\n" "$b" "$L"
  else printf "  ❌ %-28s 本地=%s 板上=%s\n" "$b" "$L" "$R"; BAD=$((BAD+1)); fi
done
echo
echo "########## 板端落盘确认 ##########"
$SSH root@$BOARD "ls -l $DST/ | tail -12; echo; du -sh $DST"
echo
[ $BAD -eq 0 ] && echo "==> 全部 10 个文件 md5 一致 ✅" || echo "==> 有 $BAD 个文件不一致 ❌"
