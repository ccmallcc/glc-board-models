#!/bin/bash
# GLC 2026-10-09: 侦察 A 板的显示与输入硬件（为"预览屏 + 交互选图"需求）
echo "=== 1. USB 设备（找触摸屏控制器 / 键鼠）==="
lsusb 2>/dev/null || echo "  (无 lsusb)"
echo
echo "=== 2. 输入设备 ==="
ls -l /dev/input/ 2>/dev/null
echo "--- /proc/bus/input/devices ---"
cat /proc/bus/input/devices 2>/dev/null | head -40
echo
echo "=== 3. DRM / 显示 ==="
ls /sys/class/drm/ 2>/dev/null
for c in /sys/class/drm/card*/card*/status; do
  [ -f "$c" ] && echo "  $c = $(cat $c)"
done
echo
echo "=== 4. I2C 总线与设备（EDID/触摸常在 i2c 上）==="
ls /dev/i2c-* 2>/dev/null
for b in /sys/bus/i2c/devices/*; do
  [ -e "$b/name" ] && echo "  $(basename $b) = $(cat $b/name 2>/dev/null)"
done
echo
echo "=== 5. 内核日志里的 hdmi / touch / input 线索 ==="
dmesg 2>/dev/null | grep -iE "hdmi|drm|touch|input|edid|i2c" | tail -25
echo
echo "=== 6. 帧缓冲 ==="
ls -l /dev/fb* 2>/dev/null || echo "  (无 /dev/fb*)"
echo
echo "=== 7. 板子上的图片目录 ==="
ls -l /root/photo/ 2>/dev/null | head
echo "--- 有没有 U 盘 / 可移动介质 ---"
lsblk 2>/dev/null | head -20
echo
echo "=== 8. PS 侧现成工具（之前做 HDMI 时留下的）==="
ls -l /root/*hdmi* /root/hdmi* 2>/dev/null
find /root -maxdepth 2 -name "*hdmi*" -o -maxdepth 2 -name "*show*" 2>/dev/null | head -10
echo RECON_UI_DONE
