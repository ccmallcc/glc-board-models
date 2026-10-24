#!/bin/bash
# V12 + V13: loopback self-test of the board->PC transport.
#   $1 = 1 to also decode each frame on the PC side (needs compressai -> WSL)
W=/mnt/e/fudanwei/工作区
DEC=""
[ "${1:-0}" = "1" ] && DEC="--decode"
python3 "$W/tools/glc_stream.py" --selftest \
  --dir "$W/v3/golden" \
  --out "$W/v12/recv" \
  --port 9123 $DEC \
  --repo "$W/GLC-main/GLC-main" \
  --model_path "$W/GLC-main/GLC-main/pretrained/GLC_image.pth.tar" \
  --device cuda 2>&1 | grep -v FutureWarning | grep -v 'warnings.warn'
