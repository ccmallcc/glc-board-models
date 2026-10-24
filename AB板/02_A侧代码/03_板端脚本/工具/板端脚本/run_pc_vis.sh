#!/bin/bash
# PC 侧：解码板端 .glc 并出图（原图 / 重建 / 并排）
# 必须在 WSL Ubuntu-22.04 跑（那里有 compressai + CUDA 直通）
set -u
export PYTHONIOENCODING=utf-8
W=/mnt/e/fudanwei/工作区
OUT=/mnt/e/fudanwei/_logs/vis
mkdir -p "$OUT"
python3 /mnt/e/fudanwei/GLC-共享包/工具/pc_decode_vis.py \
  --glc_dir "$W/_board_run/glc" \
  --ops_dir "$W/_board_run/e2e4/operands" \
  --png_dir "$W/testset/kodak_real" \
  --out_dir "$OUT" \
  --n "${N:-4}" --device "${DEV:-cpu}" \
  --json "$OUT/pc_decode_vis_${DEV:-cpu}.json" 2>&1 \
  | grep -vE "FutureWarning|warnings.warn|torch.jit|UserWarning|^\s*$" | sed 's/^/  /'
echo "--- 产物 ---"
ls -la "$OUT"
