#!/bin/sh
# GLC 2026-10-07: A板 电台前提检查 (ASCII only)
echo "=== 1) lsusb ==="
if command -v lsusb >/dev/null 2>&1; then
  lsusb | grep -i 1a86 || echo "(lsusb 里没有 1a86)"
else
  echo "(板子没有 lsusb 命令)"
fi

echo "=== 2) USB 设备 VID:PID ==="
for d in /sys/bus/usb/devices/*/; do
  v=$(cat "$d/idVendor" 2>/dev/null)
  p=$(cat "$d/idProduct" 2>/dev/null)
  if [ -n "$v" ]; then
    pr=$(cat "$d/product" 2>/dev/null)
    echo "  $v:$p  $pr"
  fi
done

echo "=== 3) /dev/ttyUSB* ==="
ls -l /dev/ttyUSB* 2>/dev/null || echo "(不存在)"

echo "=== 4) 驱动模块 ==="
lsmod | grep -E "ch341|usbserial" || echo "(未加载)"

echo "=== 5) 容器样本 ==="
ls -l /root/glc/pack/full_img0.glc 2>/dev/null || echo "(无 full_img0.glc)"
ls -l /root/glc/pack/*.glc 2>/dev/null

echo "=== 6) 位流指纹 (只读两个允许的寄存器) ==="
echo -n "PL +0x84 = "; busybox devmem 0x400C0084 32 2>/dev/null || echo "?"
echo -n "PL +0xC0 = "; busybox devmem 0x400C00C0 32 2>/dev/null || echo "?"
cat /sys/class/fpga_manager/fpga0/state 2>/dev/null

echo "=== 7) python3 / numpy ==="
python3 -c "import sys,numpy; print('python', sys.version.split()[0], 'numpy', numpy.__version__)" 2>&1
