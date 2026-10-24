#!/bin/bash
# 严谨计时：板上本地 NPU 跑 S3p1，重复 5 次，取进程墙钟 + 官方 hard 时间
set -u
BOARD=192.168.31.72
PASS=fmsh
B=/root/glc/s3p1
SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=8"

$SSH root@$BOARD "bash -s" <<'REMOTE'
cd /root/glc/s3p1

# --- 干净地确认没有 icraft-serve ---
for p in $(pgrep -f 'icraft[-]serve' 2>/dev/null); do
  echo "  杀掉残留 icraft-serve pid=$p"; kill -9 $p 2>/dev/null
done
sleep 1
if pgrep -f 'icraft[-]serve' >/dev/null 2>&1; then echo "  ⚠️ 仍有残留"; else echo "  ✅ icraft-serve 已彻底清除"; fi
(netstat -tln 2>/dev/null || ss -tln) | grep -q 9981 && echo "  ⚠️ 9981 在听" || echo "  ✅ 9981 未监听"
echo

echo "########## 进程墙钟 × 5（每次都是完整进程）##########"
for i in 1 2 3 4 5; do
  rm -rf logs; mkdir -p logs
  S=$(date +%s%N)
  /usr/bin/icraft-run --json s3_phase1_ZG.json --raw s3_phase1_ZG.raw \
     --input "in0.ftmp;in1.ftmp" --backends 'ZG330,axi://zg330aiu;Host' \
     --log_path logs --log_time > /tmp/r$i.txt 2>&1
  RC=$?
  E=$(date +%s%N)
  MS=$(( (E-S)/1000000 ))
  HARD=$(grep -oE 'total_hard_time: *[0-9.]+' /tmp/r$i.txt | head -1 | grep -oE '[0-9.]+')
  BB=$(grep -oE 'total_backbone_time: *[0-9.]+' /tmp/r$i.txt | head -1 | grep -oE '[0-9.]+')
  LJ=$(grep -oE 'Load Json Time: *[0-9.]+' /tmp/r$i.txt | head -1 | grep -oE '[0-9.]+')
  LR=$(grep -oE 'Load Raw Time: *[0-9.]+' /tmp/r$i.txt | head -1 | grep -oE '[0-9.]+')
  echo "  第 $i 次: rc=$RC  进程墙钟=${MS} ms  hard=${HARD} ms  backbone=${BB} ms  载json=${LJ} ms  载raw=${LR} ms"
done

echo
echo "########## 完整 stdout（第 5 次，看有无解释性文字）##########"
grep -vE '^opId:' /tmp/r5.txt | sed 's/^/  /'

echo
echo "########## run_time.log 头部（找字段说明）##########"
head -8 logs/*/s3_phase1_run_time.log 2>/dev/null | sed 's/^/  /'
echo "  ..."
echo "########## run_time.log 尾部 ##########"
tail -6 logs/*/s3_phase1_run_time.log 2>/dev/null | sed 's/^/  /'

echo
echo "########## 设备/位流版本 ##########"
grep -iE 'icore|device *:|bitstream|version' /tmp/r5.txt | sed 's/^/  /' | head -10
REMOTE
