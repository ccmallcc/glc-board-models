#!/bin/bash
# V3: build + run the self-contained bitstream regression set.
W=/mnt/e/fudanwei/工作区
cd "$W/GLC-main/GLC-main" || exit 2
python3 "$W/tools/v3_regression.py" \
  --repo       "$W/GLC-main/GLC-main" \
  --model_path "$W/GLC-main/GLC-main/pretrained/GLC_image.pth.tar" \
  --png_dir    "$W/testset/kodak_real" \
  --out        "$W/v3" \
  --v5_dirs    "$W/v5_real" "$W/v5" "$W/v5_full" \
  --n 6 --size 256 --q 0 1 2 3 --device cuda \
  --make --run 2>&1 | grep -v FutureWarning | grep -v 'warnings.warn'
