#!/bin/bash
# V6 baseline runner.
#   $1 = input image dir (default: the team's real photos)
#   $2 = output dir
#   $3 = q list (default "0 1 2 3")
#   $4 = 1 to save reconstruction PNGs
W=/mnt/e/fudanwei/工作区
IN="${1:-$W/GLC-main/GLC-main/test2}"
OUT="${2:-$W/v6_test2}"
QS="${3:-0 1 2 3}"
PNG="${4:-1}"
SAVE=""
[ "$PNG" = "1" ] && SAVE="--save_png"
cd "$W/GLC-main/GLC-main" || exit 2
python3 "$W/tools/v6_kodak_baseline.py" \
  --repo       "$W/GLC-main/GLC-main" \
  --model_path "$W/GLC-main/GLC-main/pretrained/GLC_image.pth.tar" \
  --input_path "$IN" \
  --out        "$OUT" \
  --q $QS --device cuda $SAVE 2>&1 \
  | grep -v FutureWarning | grep -v 'warnings.warn'
