#!/bin/bash
# 按阶段拆解的 PC 基准：CPU vs 独显（与板端 NPU 同口径）
set -u
export PYTHONIOENCODING=utf-8
cd /mnt/e/fudanwei/工作区/GLC-main/GLC-main
B=/mnt/e/fudanwei/GLC-共享包/工具/bench_pc_stages.py
R=/mnt/e/fudanwei/工作区/_board_run
mkdir -p $R
for dev in cuda cpu; do
  echo "##################### device=$dev #####################"
  python3 $B --device $dev --n 4 --warmup 2 --out $R/pc_stages_$dev.json 2>&1 \
    | grep -vE "FutureWarning|warnings.warn|torch.jit" | sed 's/^/  /'
  echo
done
