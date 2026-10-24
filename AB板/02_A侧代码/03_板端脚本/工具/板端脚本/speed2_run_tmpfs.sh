#!/bin/bash
# 编码端提速 第 2 步：把 /root/glc/run 也搬到 tmpfs
#
# 为什么：常驻引擎每张图要经这里读写约 4.3 MB 的中间张量
#   · 输入：s1 786KB + s2 16KB + s3 262KB×2×3
#   · 输出：s1 262KB+16KB + s2 262KB + s3 262KB×2×3
# 第 1 步把 pack/full_img0 搬到 /dev/shm 时，打包合计从 2011ms 掉到 804ms（−60%）。
# 这一步是同一个道理。
set -u
GLC=/root/glc
echo "############ 0) 改之前 ############"
ls -ld $GLC/run
echo -n "  run/ 大小: "; du -sh $GLC/run 2>/dev/null | cut -f1
echo -n "  实测每张: "; echo "（见下方复测）"

echo
echo "############ 1) run/ -> /dev/shm ############"
mkdir -p /dev/shm/glc_run
if [ -L $GLC/run ]; then
  echo "  已经是软链，跳过"
else
  cp -a $GLC/run/. /dev/shm/glc_run/ 2>/dev/null
  rm -rf $GLC/run
  ln -s /dev/shm/glc_run $GLC/run
  echo "  已改为软链: $GLC/run -> /dev/shm/glc_run"
fi
ls -ld $GLC/run
echo "  子目录: $(ls $GLC/run | tr '\n' ' ')"

echo
echo "############ 2) 内存 ############"
free -m | head -2 | sed 's/^/  /'

echo
echo "############ 3) 复测 7 张（与 0.700 s/张 对照）############"
cd $GLC || exit 1
rm -f batch_out/p*.glc
GLC_RSD_RESET=each python3 -u glc_batch_rsd.py \
  p1=$GLC/inputs_photo/p1.ftmp p2=$GLC/inputs_photo/p2.ftmp p3=$GLC/inputs_photo/p3.ftmp \
  p4=$GLC/inputs_photo/p4.ftmp p5=$GLC/inputs_photo/p5.ftmp p6=$GLC/inputs_photo/p6.ftmp \
  p7=$GLC/inputs_photo/p7.ftmp > /tmp/speed2.log 2>&1
echo "  rc=$?"
tr -d '\033' < /tmp/speed2.log | sed 's/\[2K//g' \
  | grep -E "每张墙钟|首张|合计墙钟|Engine 汇总|^###   p" | sed 's/^/  /'
echo RUN2TMPFS_DONE
