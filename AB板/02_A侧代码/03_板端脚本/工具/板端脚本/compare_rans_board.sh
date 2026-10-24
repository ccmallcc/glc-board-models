#!/bin/bash
# 在板子上跑 rans_board，与 compressai 逐字节比（向量已由 mk_board_vec.py 生成）
set -u
SIM=/mnt/e/fudanwei/_logs/sim
BOARD=192.168.31.72
PASS=fmsh
SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=8"
SCP="sshpass -p $PASS scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
$SSH root@$BOARD "mkdir -p /root/glc/vec"
for k in 0 1 2 3; do $SCP "$SIM/myvec_p${k}.txt" root@$BOARD:/root/glc/vec/ >/dev/null 2>&1; done
$SSH root@$BOARD 'cd /root/glc/vec && for k in 0 1 2 3; do echo "--- phase $k ---"; /root/pkg/board/rans_board myvec_p${k}.txt /root/pkg/board/glc_cdf_table.bin 2>&1 | grep -E "符号|板端输出|compressai:|逐字节|覆盖率|首个差异|结论" | sed "s/^/  /"; done'
