#!/bin/bash
# GLC 2026-10-09: 批量（常驻引擎 + CPU 打包）
#   用法: run_batch_cpu.sh [图号列表]   例: run_batch_cpu.sh 7   或   run_batch_cpu.sh
cd /root/glc || exit 1
LIST="${*:-1 2 3 4 5 6 7}"
ARGS=""
for i in $LIST; do ARGS="$ARGS p$i=/root/glc/inputs_photo/p$i.ftmp"; done
echo "=== 批量（常驻引擎 + CPU 打包）：$LIST ==="
echo "    位流指纹: $(busybox devmem 0x400C0084 32)"
python3 -u glc_batch_cpu.py $ARGS > /tmp/batch_cpu.log 2>&1
echo "rc=$?"
tr -d '\033' < /tmp/batch_cpu.log | sed 's/\[2K//g' \
  | grep -E '^###|CPU glc2_pack|Engine:|BATCH_CPU_DONE|!!|不一致|逐字节|补丁'
echo RUN_CPU_DONE
