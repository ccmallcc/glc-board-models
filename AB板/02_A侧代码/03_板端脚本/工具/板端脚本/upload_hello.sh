#!/bin/bash
# Upload the compiled hello program to the board and run it there.
# PC 192.168.0.1  <-->  board 192.168.0.2  (direct ethernet)
set -e
BOARD=192.168.0.2
USER=root
PASS=fmsh
SRC="/mnt/e/fudanwei/GLC-共享包/开发板程序模板/hello/hello_arm64"
SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
SCP="sshpass -p $PASS scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"

echo "=== 0) 本地文件 ==="
ls -l "$SRC"
file "$SRC"
md5sum "$SRC"
echo

echo "=== 1) 上传 ==="
$SCP "$SRC" "$USER@$BOARD:/root/"
echo "  done"
echo

echo "=== 2) 板子上确认 + 运行 ==="
$SSH "$USER@$BOARD" 'bash -s' <<'REMOTE'
set -e
cd /root
echo "--- 板子信息 ---"
uname -m
nproc
echo
echo "--- 文件 ---"
ls -l hello_arm64
file hello_arm64 2>/dev/null || echo "(板上没有 file 命令，正常)"
md5sum hello_arm64
echo
echo "--- chmod + 运行 ---"
chmod +x hello_arm64
./hello_arm64
REMOTE
