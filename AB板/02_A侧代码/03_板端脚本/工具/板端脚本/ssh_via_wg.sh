#!/bin/bash
# 通过 WireGuard 走 10.88.0.3 登录板子，确认身份
PASS=fmsh
SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=8"

echo "=== 从 WSL 能不能到 10.88.0.3 ==="
timeout 6 bash -c 'exec 3<>/dev/tcp/10.88.0.3/22 && head -c 60 <&3 && echo' 2>/dev/null || echo "  WSL 到不了（可能 NAT 只覆盖 WSL 自己的子网）"
echo

echo "=== 登录并确认身份 ==="
$SSH root@10.88.0.3 'bash -s' <<'REMOTE'
echo "  hostname : $(hostname)"
echo "  uname    : $(uname -m)  $(uname -r)"
echo "  nproc    : $(nproc)"
echo "  CPU      : $(grep -m1 'CPU part' /proc/cpuinfo)"
echo
echo "  --- 网络 ---"
ip -4 addr show | grep -E 'inet ' | sed 's/^/    /'
echo
echo "  --- 之前布好的东西还在吗 ---"
ls -d /root/pkg /home/work 2>/dev/null | sed 's/^/    /'
ls /usr/bin/icraft* 2>/dev/null | sed 's/^/    /'
ls /usr/lib/aarch64-linux-gnu/ 2>/dev/null | grep -c icraft | sed 's/^/    icraft 库数量: /'
python3 -c "import icraft;print('    icraft python:',icraft.__file__)" 2>&1 | tail -1
echo
echo "  --- icraft-serve 在跑吗 ---"
ps aux | grep -v grep | grep icraft-serve | sed 's/^/    /' || echo "    (没在跑)"
(netstat -tlnp 2>/dev/null || ss -tlnp) | grep -E '9981|:22 ' | sed 's/^/    /'
REMOTE
