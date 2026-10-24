#!/bin/bash
# V5 step 1: dump what the board needs to rebuild the GLC2 container
#   $1 = number of images (default 2)
#   $2 = crop size, 0 = whole image (default 0)
#   $3 = output dir (default $W/v5)
#   $4 = input image dir (default $W/testset/kodak)
W=/mnt/e/fudanwei/工作区
OUT="${3:-$W/v5}"
INDIR="${4:-$W/testset/kodak}"
cd "$W/GLC-main/GLC-main" || exit 2
echo "# input dir: $INDIR"
python3 "$W/tools/v5_dump_operands.py" \
  --repo      "$W/GLC-main/GLC-main" \
  --model_path "$W/GLC-main/GLC-main/pretrained/GLC_image.pth.tar" \
  --input_path "$INDIR" \
  --out       "$OUT" \
  --n "${1:-2}" --q 0 --device cuda --crop "${2:-0}" 2>&1 \
  | grep -v FutureWarning | grep -v 'warnings.warn'
