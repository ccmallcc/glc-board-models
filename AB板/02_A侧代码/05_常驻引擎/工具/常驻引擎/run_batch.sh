#!/bin/bash
# GLC 2026-10-08: 批量常驻编码 7 张图
cd /root/glc || exit 1
ARGS=""
for i in 1 2 3 4 5 6 7; do
  ARGS="$ARGS p$i=/root/glc/inputs_photo/p$i.ftmp"
done
echo "=== 启动：glc_batch_rsd.py$ARGS ==="
python3 -u glc_batch_rsd.py $ARGS > /tmp/batch.log 2>&1
RC=$?
echo "rc=$RC"
tr -d '\033' < /tmp/batch.log | sed 's/\[2K//g' | grep -E '^###|Engine:|BATCH_RSD_DONE|不一致'
echo BATCH_RUN_DONE
