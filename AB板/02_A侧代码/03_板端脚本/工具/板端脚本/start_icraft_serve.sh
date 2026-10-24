#!/bin/bash
# 在板子上启动 icraft-serve（把 NPU 暴露成 socket 后端），供 PC 侧 icraft-run 调用
PASS=fmsh
SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
$SSH root@192.168.0.2 'bash -s' <<'REMOTE'
set +e
pkill -f icraft-serve 2>/dev/null; sleep 1
cd /root
nohup /usr/bin/icraft-serve --port 9981 > /root/icraft-serve.log 2>&1 &
sleep 4
echo "########## 进程 ##########"
ps aux | grep -v grep | grep icraft-serve || echo "  (没起来)"
echo
echo "########## 端口 ##########"
(netstat -tlnp 2>/dev/null || ss -tlnp) | grep -E '9981|LISTEN' | head
echo
echo "########## 服务日志 ##########"
cat /root/icraft-serve.log 2>/dev/null | head -40
echo
echo "########## 从本地自己连一下 ##########"
timeout 5 bash -c 'exec 3<>/dev/tcp/127.0.0.1/9981 && echo "  9981 可连"' 2>/dev/null || echo "  9981 连不上"
REMOTE
