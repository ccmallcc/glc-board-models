#!/bin/sh
# 板端：4 个样本逐个跑「整条编码侧」(NPU + 胶水 + PL)，每个都做三方对拍
cd /root/glc || exit 1
for i in 0 1 2 3; do
  echo "################################################################"
  echo "##########  sample $i  ##########"
  echo "################################################################"
  cp /root/glc/inputs/s${i}_in0.ftmp /root/glc/run/s1/in0.ftmp || exit 1
  python3 glc_board_full.py --sample $i 2>&1 | grep -vE '^\[2026'
  echo
  sh /root/glc/pack_full.sh $i
  echo
done

echo "################################################################"
echo "##########  容器 md5 三方总汇  ##########"
echo "################################################################"
echo "--- 板端全链路(PL) ---"
md5sum /root/glc/pack/full_img0.glc /root/glc/pack/full_img1.glc \
       /root/glc/pack/full_img2.glc /root/glc/pack/full_img3.glc 2>/dev/null
echo "--- PC 链路参考 ---"
md5sum /root/glc/pack/img0.glc /root/glc/pack/img1.glc \
       /root/glc/pack/img2.glc /root/glc/pack/img3.glc 2>/dev/null
echo "--- 尺寸 ---"
ls -l /root/glc/pack/full_img?.glc /root/glc/pack/img?.glc 2>/dev/null
