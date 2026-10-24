#!/bin/bash
# W2: measure the board-side native-C++ rANS cost (the number that was never measured).
BOARD=192.168.0.2; USER=root; PASS=fmsh
SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
$SSH "$USER@$BOARD" 'bash -s' <<'REMOTE'
cd /root/pkg/rans

echo "=== CPU 信息 ==="
nproc
grep -E 'CPU part|BogoMIPS|Features' /proc/cpuinfo | sort -u
echo "cpufreq:"; ls /sys/devices/system/cpu/cpu0/cpufreq/ 2>/dev/null || echo "  (无 cpufreq，频率不可调/不可读)"
echo

echo "=== 计时工具探测 ==="
command -v /usr/bin/time && echo "has /usr/bin/time" || echo "no /usr/bin/time"
date +%s%N >/dev/null 2>&1 && echo "date +%s%N 可用" || echo "date +%s%N 不可用"
echo

timeit() {           # $1=二进制 $2=参数 ; 输出纳秒
  local t0 t1
  t0=$(date +%s%N)
  "$@" >/dev/null 2>&1
  t1=$(date +%s%N)
  echo $(( t1 - t0 ))
}

echo "=== W2：rANS 编码耗时（每档跑 5 次取最好）==="
printf '%-9s %-11s %-10s %s\n' 向量 符号数 best_ms ns/符号
for v in phase0 phase1 phase2 phase3 stress; do
  case $v in phase0|phase1|phase2|phase3) n=16384;; stress) n=2504;; esac
  best=999999999
  for i in 1 2 3 4 5; do
    ns=$(timeit ./rans_port "vector_$v.txt")
    [ "$ns" -lt "$best" ] && best=$ns
  done
  awk -v v="$v" -v n="$n" -v b="$best" 'BEGIN{printf "%-9s %-11d %-10.2f %.2f\n", v, n, b/1e6, b/n}'
done
echo

echo "=== 对照：同一次开机的 bench/hello（用于标定 A53 与 i9 的比）==="
ns=$(timeit /root/pkg/hello_arm64); echo "hello 1e7 次累加 : $(awk -v b=$ns 'BEGIN{printf "%.1f ms", b/1e6}')"
REMOTE
