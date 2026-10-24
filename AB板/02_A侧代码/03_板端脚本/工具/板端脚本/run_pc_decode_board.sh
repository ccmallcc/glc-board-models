#!/bin/bash
# 在 WSL（有 compressai）里解码板端产的 .glc
set -u
export PYTHONIOENCODING=utf-8
cd /mnt/e/fudanwei/工作区/GLC-main/GLC-main
R=/mnt/e/fudanwei/工作区/_board_run
for dev in cpu cuda; do
  echo "##################### device=$dev #####################"
  python3 /mnt/e/fudanwei/GLC-共享包/工具/pc_decode_board.py \
    --glc_dir $R/glc \
    --ops_dir $R/e2e4/operands \
    --png_dir /mnt/e/fudanwei/工作区/testset/kodak_real \
    --n 4 --device $dev \
    --out $R/pc_decode_board_$dev.json 2>&1 \
    | grep -vE "FutureWarning|warnings.warn|torch.jit" | sed 's/^/  /'
  echo
done
