#!/bin/bash
# 直连以太网到板子：连通性 + 身份 + 磁盘 + 吞吐
BOARD=192.168.31.72
PASS=fmsh
SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=8"

echo "=== WSL 能不能到板子 ==="
ping -c 2 -W 2 $BOARD 2>&1 | tail -3

echo
echo "=== 登录 ==="
$SSH root@$BOARD 'bash -s' <<'REMOTE'
echo "  hostname : $(hostname)"
echo "  uname    : $(uname -m) $(uname -r)"
echo "  nproc    : $(nproc)"
echo "  uptime   :$(uptime | sed 's/^.*up//;s/,.*load/ load/')"
echo
echo "  --- 网络 ---"
ip -4 addr show | grep -E 'inet ' | sed 's/^/    /'
for i in $(ls /sys/class/net | grep -v lo); do
  s=$(cat /sys/class/net/$i/speed 2>/dev/null); echo "    $i speed=${s:-?} Mbps"
done
echo
echo "  --- runtime ---"
ls /usr/bin/icraft* 2>/dev/null | sed 's/^/    /'
ls /usr/lib/aarch64-linux-gnu/ 2>/dev/null | grep -c icraft | sed 's/^/    icraft 库: /'
ls /usr/lib/aarch64-linux-gnu/libaxizg330aiu.so 2>/dev/null | sed 's/^/    本地设备: /'
python3 -c "import icraft;print('    icraft python:',icraft.__file__)" 2>&1 | tail -1
echo
echo "  --- 磁盘（要放 203 MB 产物）---"
df -h / /home /root 2>/dev/null | sed 's/^/    /'
echo
echo "  --- 已在板上的东西 ---"
ls -d /root/pkg /home/work 2>/dev/null | sed 's/^/    /'
du -sh /root/pkg /home/work 2>/dev/null | sed 's/^/    /'
REMOTE
