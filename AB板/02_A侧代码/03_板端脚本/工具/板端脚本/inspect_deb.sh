#!/bin/bash
# 看清 deb 装什么 → 装 runtime → 重试 import + 开 NPU 设备
PASS=fmsh
SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
$SSH root@192.168.0.2 'bash -s' <<'REMOTE'
cd /home/work

echo "########## A. deb 元信息 ##########"
dpkg-deb -I Icraft_3.36.1_onchip.deb 2>&1 | head -20
echo "--- 会装哪些文件（前 40）---"
dpkg-deb -c Icraft_3.36.1_onchip.deb 2>&1 | head -40
echo "--- 装了多少个文件 ---"
dpkg-deb -c Icraft_3.36.1_onchip.deb 2>&1 | wc -l
echo
echo "--- CustomOp deb ---"
dpkg-deb -I CustomOp_3.36.1_onchip.deb 2>&1 | head -12
dpkg-deb -c CustomOp_3.36.1_onchip.deb 2>&1 | head -20
REMOTE
