#!/bin/bash
# 隔着 WireGuard 在板子上启动 icraft-serve
PASS=fmsh
SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=8"
$SSH root@10.88.0.3 'bash -s' <<'REMOTE'
pkill -f icraft-serve 2>/dev/null; sleep 1
cd /root
nohup /usr/bin/icraft-serve --port 9981 > /root/icraft-serve.log 2>&1 &
sleep 4
echo "--- 进程 ---"
ps aux | grep -v grep | grep icraft-serve | sed 's/^/  /' || echo "  (没起来)"
echo "--- 端口 ---"
(netstat -tlnp 2>/dev/null || ss -tlnp) | grep 9981 | sed 's/^/  /'
echo "--- 日志 ---"
head -6 /root/icraft-serve.log | sed 's/^/  /'
REMOTE