#!/bin/bash
# 板上逐子图单独计时：进程墙钟 / hard / backbone / 载模型
set -u
BOARD=192.168.31.72
PASS=fmsh
SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=8"
$SSH root@$BOARD "bash -s" <<'REMOTE'
M=/root/glc/models
R=/root/glc/run
echo "########## 逐子图：3 次重复 ##########"
for spec in "s1:s1_encoder_ga_hyper" "s2:s2_hyperdec_fusion" "s3p1:s3_phase1" "s3p2:s3_phase2" "s3p3:s3_phase3"; do
  d=${spec%%:*}; n=${spec##*:}
  cd $R/$d 2>/dev/null || { echo "  跳过 $d（无目录）"; continue; }
  rm -rf logs; mkdir -p logs
  ins=$(ls in*.ftmp 2>/dev/null | tr '\n' ';' | sed 's/;$//')
  [ -z "$ins" ] && { echo "  跳过 $d（无输入）"; continue; }
  printf "  %-6s raw=%6s MB  输入=%s\n" "$d" \
     "$(awk -v s=$(stat -c%s $M/${n}_ZG.raw) 'BEGIN{printf "%.1f",s/1048576}')" "$ins"
  for i in 1 2 3; do
    S=$(date +%s%N)
    /usr/bin/icraft-run --json $M/${n}_ZG.json --raw $M/${n}_ZG.raw \
      --input "$ins" --backends 'ZG330,axi://zg330aiu;Host' \
      --log_path logs --log_time > /tmp/o.txt 2>&1
    RC=$?
    E=$(date +%s%N)
    MS=$(( (E-S)/1000000 ))
    H=$(grep -oE 'total_hard_time: *[0-9.]+' /tmp/o.txt | head -1 | grep -oE '[0-9.]+')
    B=$(grep -oE 'total_backbone_time: *[0-9.]+' /tmp/o.txt | head -1 | grep -oE '[0-9.]+')
    LJ=$(grep -oE 'Load Json Time: *[0-9.]+' /tmp/o.txt | head -1 | grep -oE '[0-9.]+')
    LR=$(grep -oE 'Load Raw Time: *[0-9.]+' /tmp/o.txt | head -1 | grep -oE '[0-9.]+')
    OPS=$(grep -cE '^opId:' /tmp/o.txt)
    echo "     第$i 次 rc=$RC  墙钟=${MS}ms  hard=${H}ms  backbone=${B}ms  载json=${LJ}ms 载raw=${LR}ms 算子行=${OPS}"
  done
done

echo
echo "########## 板上是否全为硬算子（无软算子回退）##########"
for spec in "s1:s1_encoder_ga_hyper" "s2:s2_hyperdec_fusion" "s3p1:s3_phase1" "s3p2:s3_phase2" "s3p3:s3_phase3"; do
  d=${spec%%:*}; n=${spec##*:}
  cd $R/$d 2>/dev/null || continue
  ins=$(ls in*.ftmp 2>/dev/null | tr '\n' ';' | sed 's/;$//')
  rm -rf lg; mkdir -p lg
  /usr/bin/icraft-run --json $M/${n}_ZG.json --raw $M/${n}_ZG.raw \
    --input "$ins" --backends 'ZG330,axi://zg330aiu;Host' --log_path lg --log_time > /tmp/o2.txt 2>&1
  H=$(grep -cE '\(H\)' /tmp/o2.txt)
  SOFT=$(grep -E '^opId:' /tmp/o2.txt | grep -vcE '\(H\)')
  OTH=$(grep -E '^opId:' /tmp/o2.txt | grep -vE '\(H\)' | head -3 | sed 's/^/        /')
  printf "  %-6s 硬算子行=%s  非硬算子行=%s\n" "$d" "$H" "$SOFT"
  [ -n "$OTH" ] && echo "$OTH"
done
REMOTE
