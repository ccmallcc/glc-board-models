#!/bin/bash
# decode with selectable s4 dir + extra icraft-run flags
# usage: bash run_s4b.sh <s4_dir> <list> [tag] [extra flags...]
cd /root/glcdec || exit 1
export GLC_S4_DIR="${1:-s4_int8}"
LIST="${2:-1}"
TAG="${3:-$GLC_S4_DIR}"
shift 3 2>/dev/null || shift $#
export GLC_RUN_EXTRA="$*"
OUT=/root/dec_out
mkdir -p "$OUT"

echo "=== env ==="
echo -n "  bitstream +0x84 = "; busybox devmem 0x400C0084 32
echo "  GLC_S4_DIR     = $GLC_S4_DIR"
echo "  GLC_RUN_EXTRA  = [$GLC_RUN_EXTRA]"
ls -l "/root/glc/models/$GLC_S4_DIR/" | awk 'NR>1{printf "    %s  %s B\n",$9,$5}'
echo -n "  mem: "; free -m | awk 'NR==2{printf "total %s MB / avail %s MB\n",$2,$7}'

for i in $(echo "$LIST" | tr ',' ' '); do
  GLC="/root/photos_glc/p$i.glc"
  REF="/root/glc/inputs_photo/p$i.ftmp"
  [ -f "$GLC" ] || { echo "!! missing $GLC"; continue; }
  echo "============================================================"
  echo "### p$i  container $(stat -c%s "$GLC") B  tag=$TAG"
  echo "============================================================"
  sync; echo 1 > /proc/sys/vm/drop_caches 2>/dev/null
  T0=$(date +%s)
  python3 -u decode_board.py "$GLC" --npz "$OUT/${TAG}_p$i.npz" --out "$OUT/${TAG}_p$i.png" 2>&1 | tail -32
  RC=${PIPESTATUS[0]}
  T1=$(date +%s)
  echo "  decode rc=$RC  wall=$((T1-T0)) s"
  echo -n "  mem after: "; free -m | awk 'NR==2{print $7" MB avail"}'
  if [ -f "$OUT/${TAG}_p$i.npz" ]; then
    python3 /root/glcdec/psnr_check.py "$OUT/${TAG}_p$i.npz" "$REF" "p$i($TAG)"
  fi
  echo
done
echo S4RUNB_DONE
