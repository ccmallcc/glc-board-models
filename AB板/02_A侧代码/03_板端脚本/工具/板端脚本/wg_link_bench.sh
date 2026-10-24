#!/bin/bash
# 量 WireGuard 这条路的延迟与吞吐
PASS=fmsh; HOST=10.88.0.3
SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=8"
SCP="sshpass -p $PASS scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"

echo "=== A. ICMP 延迟（10 次）==="
for i in 1 2 3 4 5 6 7 8 9 10; do
  t0=$(date +%s%N)
  $SSH root@$HOST 'true' 2>/dev/null
  t1=$(date +%s%N)
  printf '  ssh 往返 #%d: %d ms\n' $i $(( (t1-t0)/1000000 ))
done

echo
echo "=== B. TCP 吞吐（scp 传 20 MB）==="
dd if=/dev/urandom of=/tmp/wgtest.bin bs=1M count=20 status=none
ls -l /tmp/wgtest.bin | awk '{print "  本地文件:", $5, "bytes"}'
t0=$(date +%s%N)
$SCP /tmp/wgtest.bin root@$HOST:/tmp/ 2>/dev/null
t1=$(date +%s%N)
ms=$(( (t1-t0)/1000000 ))
echo "  用时: ${ms} ms"
awk -v ms=$ms 'BEGIN{ printf "  上行吞吐 ≈ %.2f MB/s = %.1f Mbit/s\n", 20/(ms/1000), 20*8/(ms/1000) }'

t0=$(date +%s%N)
$SCP root@$HOST:/tmp/wgtest.bin /tmp/wgtest_back.bin 2>/dev/null
t1=$(date +%s%N)
ms2=$(( (t1-t0)/1000000 ))
echo "  回程用时: ${ms2} ms"
awk -v ms=$ms2 'BEGIN{ printf "  下行吞吐 ≈ %.2f MB/s = %.1f Mbit/s\n", 20/(ms/1000), 20*8/(ms/1000) }'

$SSH root@$HOST 'rm -f /tmp/wgtest.bin' 2>/dev/null
rm -f /tmp/wgtest.bin /tmp/wgtest_back.bin

echo
echo "=== C. 板子那一侧的网络（它自己怎么连出去的）==="
$SSH root@$HOST 'bash -s' <<'REMOTE'
ip -4 route | sed 's/^/    /'
echo "    --- wg 接口 ---"
ip -d link show wg1 2>/dev/null | head -5 | sed 's/^/    /'
echo "    --- eth0 速率 ---"
cat /sys/class/net/eth0/speed 2>/dev/null | sed 's/^/    eth0 speed = /;s/$/ Mbps/'
cat /sys/class/net/wg1/mtu 2>/dev/null | sed 's/^/    wg1 mtu = /'
REMOTE
