#!/bin/bash
# V7: perceptual metrics (LPIPS-Alex / DISTS / MS-SSIM) on the REAL bitstream.
#   $1 = input image dir (default: real Kodak 24)
#   $2 = output dir
#   $3 = q list
W=/mnt/e/fudanwei/工作区
IN="${1:-$W/testset/kodak_real}"
OUT="${2:-$W/v7_kodak}"
QS="${3:-0 1 2 3}"
cd "$W/GLC-main/GLC-main" || exit 2
python3 "$W/tools/v7_perceptual.py" \
  --mode bitstream \
  --repo       "$W/GLC-main/GLC-main" \
  --model_path "$W/GLC-main/GLC-main/pretrained/GLC_image.pth.tar" \
  --input_path "$IN" \
  --out        "$OUT" \
  --q $QS --device cuda 2>&1 \
  | grep -v FutureWarning | grep -v 'warnings.warn'
