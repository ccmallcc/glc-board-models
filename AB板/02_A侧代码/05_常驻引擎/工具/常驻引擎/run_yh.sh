#!/bin/bash
cd /root/glc || exit 1
ARGS=""
for i in 1 2 3 4 5 6 7; do
  ARGS="$ARGS p$i=/root/glc/inputs_photo/p$i.ftmp"
done
echo "=== y_hat 统计：7 张 ==="
GLC_RSD_RESET=each python3 -u /root/glc/glc_yh_stats.py $ARGS > /tmp/yh.log 2>&1
echo "rc=$?"
tr -d '\033' < /tmp/yh.log | sed 's/\[2K//g' | grep -E 'y_hat|分位|超 ±|汇总|^   p[0-9]|-> p[0-9]|已写|YH_STATS_DONE|!!|补丁|引擎'
echo YH_RUN_DONE
