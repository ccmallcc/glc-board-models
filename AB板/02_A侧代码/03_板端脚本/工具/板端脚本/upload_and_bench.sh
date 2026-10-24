#!/bin/bash
# Upload the v1/v2 rANS regression bundle + bench to the board and measure W2.
set -e
BOARD=192.168.0.2; USER=root; PASS=fmsh
B="/mnt/e/fudanwei/开发板传输包"
SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
SCP="sshpass -p $PASS scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"

echo "=== 建目录 ==="
$SSH "$USER@$BOARD" 'mkdir -p /root/pkg/rans /root/pkg/board && echo ok'

echo "=== 上传（目标路径全 ASCII，避开中文目录名）==="
$SCP "$B/1_hello/hello_arm64" "$B/2_bench/bench_arm64"      "$USER@$BOARD:/root/pkg/"
$SCP "$B/3_rANS内核/rans_port" "$B/3_rANS内核/"vector_*.txt "$B/3_rANS内核/run.sh" "$USER@$BOARD:/root/pkg/rans/"
$SCP "$B/4_板端回归/rans_board" "$B/4_板端回归/glc_cdf_table.bin" "$B/4_板端回归/"boardvec_*.txt "$B/4_板端回归/run.sh" "$USER@$BOARD:/root/pkg/board/"
echo "  done"

echo
echo "=== 板子环境 ==="
$SSH "$USER@$BOARD" 'nproc; grep -m1 "model name" /proc/cpuinfo; grep -m1 "BogoMIPS" /proc/cpuinfo; \
  for c in /sys/devices/system/cpu/cpu0/cpufreq; do [ -d $c ] && echo "cpufreq: $(cat $c/scaling_cur_freq 2>/dev/null) kHz" || echo "cpufreq: 无"; done; \
  cat /proc/version'

echo
echo "=== 板子上跑（含 W2 计时）==="
$SSH "$USER@$BOARD" 'bash -s' <<'REMOTE'
set -e
cd /root/pkg
chmod +x hello_arm64 bench_arm64 rans/rans_port board/rans_board

echo "########## 1) hello ##########"
./hello_arm64
echo
echo "########## 2) bench 模板 ##########"
./bench_arm64
echo
echo "########## 3) V1 rANS 内核（逐字节对拍）##########"
cd rans && bash run.sh 2>&1 | tail -6
echo
echo "########## 4) W2：板端原生 C++ 的 AE 耗时 ##########"
for v in phase0 stress; do
  printf '%-8s ' "$v"
  # 跑 5 次取最好成绩（避免调度抖动）
  best=999999
  for i in 1 2 3 4 5; do
    s=$( { /usr/bin/time -f %e ./rans_port "vector_$v.txt" >/dev/null; } 2>&1 )
    best=$(echo "$best $s" | awk '{print ($2<$1)?$2:$1}')
  done
  n=$( [ "$v" = phase0 ] && echo 16384 || echo 2504 )
  echo "best=${best}s  符号数=$n  ->  $(echo "$best $n" | awk '{printf "%.2f", $1*1e9/$2}') ns/符号"
done
echo
echo "########## 5) V2 板端路径回归 ##########"
cd ../board && bash run.sh 2>&1
REMOTE
