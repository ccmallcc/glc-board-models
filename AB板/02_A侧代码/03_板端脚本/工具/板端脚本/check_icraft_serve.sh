#!/bin/bash
# 装完 deb 后，板子上多了哪些命令？icraft-serve 是什么？
PASS=fmsh
SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
$SSH root@192.168.0.2 'bash -s' <<'REMOTE'
echo "########## A. 新装的命令 ##########"
ls -l /usr/bin/icraft*
echo
echo "########## B. icraft-serve --help ##########"
timeout 20 /usr/bin/icraft-serve --help 2>&1 | head -40
echo "(exit=$?)"
echo
echo "########## C. icraft-run --help（看 backends 语法）##########"
timeout 20 /usr/bin/icraft-run --help 2>&1 | grep -i -A3 -B1 'backend\|socket\|device' | head -40
echo
echo "########## D. icraft --help ##########"
timeout 20 /usr/bin/icraft --help 2>&1 | head -30
REMOTE
