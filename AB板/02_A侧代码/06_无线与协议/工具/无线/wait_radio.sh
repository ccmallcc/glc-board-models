#!/bin/bash
# GLC 2026-10-07: 等电台插入 -> 自动跑 A_send.py --check-only
# 用法: bash /root/wait_radio.sh [等待秒数=2400] [轮询间隔=10]
WAIT=${1:-2400}
STEP=${2:-10}
N=$((WAIT/STEP))
echo "[waiter] 开始等待 /dev/ttyUSB0，最多 ${WAIT}s（每 ${STEP}s 查一次）"
found=0
for i in $(seq 1 $N); do
  if [ -e /dev/ttyUSB0 ]; then found=1; break; fi
  sleep $STEP
done

if [ "$found" != "1" ]; then
  echo "[waiter] TIMEOUT: ${WAIT}s 内没有等到 /dev/ttyUSB0"
  echo "[waiter] 当前 USB 设备:"
  for d in /sys/bus/usb/devices/*/; do
    v=$(cat "$d/idVendor" 2>/dev/null)
    p=$(cat "$d/idProduct" 2>/dev/null)
    [ -n "$v" ] && echo "   $v:$p"
  done
  exit 1
fi

echo "[waiter] *** 检测到 /dev/ttyUSB0 ***"
ls -l /dev/ttyUSB0
echo "[waiter] USB 设备列表:"
for d in /sys/bus/usb/devices/*/; do
  v=$(cat "$d/idVendor" 2>/dev/null)
  p=$(cat "$d/idProduct" 2>/dev/null)
  pr=$(cat "$d/product" 2>/dev/null)
  [ -n "$v" ] && echo "   $v:$p  $pr"
done
echo "[waiter] dmesg 尾部:"
dmesg | tail -6
echo "[waiter] === 跑 A_send.py --check-only ==="
python3 /root/A_send.py --check-only
echo "[waiter] DONE rc=$?"
