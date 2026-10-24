#!/bin/bash
# PC 端全链路基准：独显 vs CPU（同一份代码、同一台机器）
set -u
export PYTHONIOENCODING=utf-8
cd /mnt/e/fudanwei/工作区/GLC-main/GLC-main
B=/mnt/e/fudanwei/GLC-共享包/工具/bench_pc_chain.py
R=/mnt/e/fudanwei/工作区/_board_run
mkdir -p $R
for dev in cuda cpu; do
  echo "##################### device=$dev #####################"
  python3 $B --device $dev --n 4 --warmup 2 \
     --out $R/pc_chain_$dev.json 2>&1 \
     | grep -vE "FutureWarning|warnings.warn|torch.jit" | sed 's/^/  /'
  echo
done
