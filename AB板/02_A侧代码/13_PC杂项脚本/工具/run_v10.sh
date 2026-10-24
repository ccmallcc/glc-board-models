#!/bin/bash
# V10: 512x512 entropy coding and stream composition.
#   $1 = crop size (default 512)
W=/mnt/e/fudanwei/工作区
C="${1:-512}"
cd "$W/GLC-main/GLC-main" || exit 2
python3 "$W/tools/v6_kodak_baseline.py" \
  --repo       "$W/GLC-main/GLC-main" \
  --model_path "$W/GLC-main/GLC-main/pretrained/GLC_image.pth.tar" \
  --input_path "$W/testset/kodak_real" \
  --out        "$W/v10_$C" \
  --q 0 1 2 3 --device cuda --crop "$C" 2>&1 \
  | grep -v FutureWarning | grep -v 'warnings.warn' \
  | grep -E 'AVERAGE|device=|->|skip'
