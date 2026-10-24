#!/bin/bash
# V5 step 3+4: independent container validation, then decode with compressai.
#   $1 = v5 dir (default $W/v5), $2 = n images, $3 = crop (0 = whole image)
W=/mnt/e/fudanwei/工作区
V="${1:-$W/v5}"
N="${2:-4}"
CROP="${3:-256}"
cd "$W/GLC-main/GLC-main" || exit 2
echo "########## 独立校验器（不依赖 torch / compressai）##########"
python3 "$W/tools/glc2_validate.py" --root "$V" 2>&1 | tail -14
echo
echo "########## 用 compressai 解码自产容器 ##########"
python3 "$W/tools/v5_verify.py" \
  --repo "$W/GLC-main/GLC-main" \
  --model_path "$W/GLC-main/GLC-main/pretrained/GLC_image.pth.tar" \
  --input_path "$W/testset/kodak" \
  --v5 "$V" --n "$N" --crop "$CROP" --device cuda 2>&1 \
  | grep -v FutureWarning | grep -v 'warnings.warn'
