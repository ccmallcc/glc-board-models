#!/bin/bash
#=============================================================================
# enc_batch.sh —— 批量编码（**自动选最快的路**）
#
#   bash /root/enc_batch.sh p1=/root/glc/inputs_photo/p1.ftmp p2=... 
#   bash /root/enc_batch.sh --dir /root/photo            # 目录里所有 jpg/png
#   bash /root/enc_batch.sh --force-cpu p1=...           # 强制走 A53 CPU 打包
#
# 路径选择（实测，A 板，256×256）：
#   位流指纹 = 0x20260922（我们的 rans_top） ⇒ glc_batch_rsd.py  PL rANS  0.715 s/张
#   否则                                      ⇒ glc_batch_cpu.py  CPU 打包 0.894 s/张
# 两者的容器**逐字节一致**（p1~p4 md5 全对）。
#
# 前置：先跑一次 /root/speed_setup.sh（把操作数目录和 /tmp 搬到 tmpfs，
#       这一项单独就值 ~0.3 s/张）。本脚本会自己调它，幂等。
#=============================================================================
set -u
GLC=/root/glc
OUT=$GLC/batch_out
FORCE=cpu

# ---------------------------------------------------------------- 参数
ARGS=""
while [ $# -gt 0 ]; do
  case "$1" in
    --force-cpu) FORCE=cpu; shift ;;
    --force-pl)  FORCE=pl;  shift ;;
    --dir)
      d="$2"; shift 2
      i=0
      for f in "$d"/*.jpg "$d"/*.jpeg "$d"/*.png; do
        [ -f "$f" ] || continue
        i=$((i+1))
        n=$(basename "$f"); n="${n%.*}"
        # 需要先预处理成 ftmp
        python3 /root/enc_image.py "$f" --out /dev/shm/in_$n.ftmp >/dev/null 2>&1 \
          && ARGS="$ARGS $n=/dev/shm/in_$n.ftmp"
      done
      echo "  从 $d 收了 $i 张图"
      ;;
    --*=*|*) ARGS="$ARGS $1"; shift ;;
  esac
done
[ -n "$ARGS" ] || { echo "用法: bash /root/enc_batch.sh p1=/path/a.ftmp ... | --dir <图片目录>"; exit 2; }

# ---------------------------------------------------------------- 环境
sh /root/speed_setup.sh 2>/dev/null | grep -E "已是|已建立|已挂载|已补|✅|⚠️|GLC_ENC_PATH" | sed 's/^/  /'
FP=$(busybox devmem 0x400C0084 32 2>/dev/null || echo "?")
if [ "$FORCE" = "pl" ] && [ "$FP" != "0x20260922" ]; then
  echo "  !! --force-pl 但指纹是 $FP，PL rANS 会被拒 —— 改成 CPU"
  FORCE=cpu
fi
if [ "$FORCE" != "pl" ] && [ "$FP" = "0x20260922" ]; then
  FORCE=pl
fi

if [ "$FORCE" = "pl" ]; then
  SCRIPT=glc_batch_rsd.py;  LABEL="PL rANS（FPGA）"; OUT=$GLC/batch_out
else
  SCRIPT=glc_batch_cpu.py;  LABEL="A53 CPU 打包";    OUT=$GLC/batch_out_cpu
fi
echo
echo "############ 批量编码：$LABEL ｜ 指纹 $FP ############"

# ---------------------------------------------------------------- 跑
cd $GLC || exit 1
# shellcheck disable=SC2086
S=$(date +%s)
GLC_RSD_RESET=each python3 -u $SCRIPT $ARGS > /tmp/enc_batch.log 2>&1
RC=$?
E=$(date +%s)
echo "  rc=$RC  总墙钟 $((E-S)) s"
tr -d '\033' < /tmp/enc_batch.log | sed 's/\[2K//g' \
  | grep -E "单张墙钟|每张墙钟|首张|合计墙钟|Engine 汇总|PL rANS 实测|容器清单|^###   " \
  | sed 's/^/  /'

echo
echo "############ 产物（把这几行发给 B 核对）############"
printf "  %-14s %6s  %s\n" "名字" "字节" "md5"
for f in $OUT/*.glc; do
  [ -e "$f" ] || continue
  printf "  %-14s %6d  %s\n" "$(basename "$f")" "$(stat -c%s "$f")" "$(md5sum "$f" | cut -d' ' -f1)"
done
echo ENC_BATCH_DONE
