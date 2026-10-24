#!/bin/bash
# GLC 2026-10-10: A 板独立复现 **int8 单图解码** 并算 PSNR（B 要的交付物 #4）
#   用法: bash run_dec_int8.sh [图号列表，逗号分隔]   默认 1,2
cd /root/glcdec || exit 1
LIST="${1:-1,2}"
OUT=/root/dec_out
mkdir -p $OUT

echo "=== 环境 ==="
echo -n "  位流 +0x84 = "; busybox devmem 0x400C0084 32
echo -n "  s4_int8  : "; ls -l /root/glc/models/s4_int8/ | awk 'NR>1{printf "%s(%s B) ", $9, $5}'; echo
echo -n "  内存     : "; free -m | awk 'NR==2{printf "总 %s MB / 可用 %s MB\n", $2, $7}'
echo

for i in $(echo "$LIST" | tr ',' ' '); do
  GLC=/root/photos_glc/p$i.glc
  REF=/root/glc/inputs_photo/p$i.ftmp
  [ -f "$GLC" ] || { echo "!! 缺容器 $GLC"; continue; }
  echo "============================================================"
  echo "### p$i  容器 $(stat -c%s $GLC) B  md5=$(md5sum $GLC | cut -d' ' -f1)"
  echo "============================================================"
  # 先释放 page cache，避免内存紧张（B 就是被 OOM 杀的）
  sync; echo 1 > /proc/sys/vm/drop_caches 2>/dev/null
  echo -n "  解码前可用内存: "; free -m | awk 'NR==2{print $7" MB"}'
  T0=$(date +%s)
  python3 -u decode_board.py "$GLC" --npz $OUT/p$i.npz --out $OUT/p$i.png 2>&1 | tail -25
  RC=$?
  T1=$(date +%s)
  echo "  decode rc=$RC  用时 $((T1-T0)) s"
  echo -n "  解码后可用内存: "; free -m | awk 'NR==2{print $7" MB"}'
  if [ -f "$OUT/p$i.npz" ]; then
    python3 /root/glcdec/psnr_check.py $OUT/p$i.npz "$REF" "p$i(int8)"
  fi
  echo
done
echo "=== 产物 ==="
ls -l $OUT/ 2>/dev/null
echo DEC_INT8_DONE
