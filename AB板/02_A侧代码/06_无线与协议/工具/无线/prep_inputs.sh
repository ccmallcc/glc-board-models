#!/bin/bash
# GLC 2026-10-08: 为批量常驻编码准备 7 张图的输入张量
set -u
mkdir -p /root/glc/inputs_photo
for i in 1 2 3 4 5 6 7; do
  f=/root/photo/p$i.jpg
  [ -f "$f" ] || { echo "缺 $f"; continue; }
  python3 /root/enc_image.py "$f" --mode fit --out /root/glc/inputs_photo/p$i.ftmp \
      2>/dev/null | grep -E '原图|张量|已写'
done
echo "=== 生成结果 ==="
ls -l /root/glc/inputs_photo/
md5sum /root/glc/inputs_photo/*.ftmp
echo PREP_DONE
