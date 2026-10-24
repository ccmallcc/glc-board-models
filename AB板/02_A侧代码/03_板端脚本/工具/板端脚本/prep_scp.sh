#!/bin/bash
# Prepare to scp to the board from WSL.
echo "=== WSL 能不能到板子 ==="
ping -c 2 -W 2 192.168.0.2 || echo "PING FAILED"
echo
echo "=== 22 端口 ==="
(exec 3<>/dev/tcp/192.168.0.2/22 && echo "port 22 OPEN" && head -c 40 <&3; echo) 2>/dev/null || echo "port 22 unreachable"
echo
echo "=== sshpass ==="
if command -v sshpass >/dev/null 2>&1; then
  echo "already: $(command -v sshpass)"
else
  echo "installing ..."
  apt-get install -y -q sshpass >/tmp/apt_sp.log 2>&1 && echo "installed OK" || { echo "INSTALL FAILED"; tail -5 /tmp/apt_sp.log; }
fi
command -v sshpass && sshpass -V 2>&1 | head -1
echo
echo "=== ssh client ==="
ssh -V 2>&1
