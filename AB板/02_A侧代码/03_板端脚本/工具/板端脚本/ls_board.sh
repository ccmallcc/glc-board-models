#!/bin/bash
# Show exactly what landed on the board.
PASS=fmsh
SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
$SSH root@192.168.0.2 'bash -s' <<'REMOTE'
echo "--- /root ---"
ls -l /root/
echo
echo "--- /root/pkg ---"
ls -l /root/pkg/
echo
echo "--- /root/pkg/rans ---"
ls -l /root/pkg/rans/
echo
echo "--- /root/pkg/board ---"
ls -l /root/pkg/board/
echo
echo "--- 架构确认 ---"
file /root/hello_arm64 2>/dev/null || echo "(板上无 file 命令)"
md5sum /root/hello_arm64
REMOTE
