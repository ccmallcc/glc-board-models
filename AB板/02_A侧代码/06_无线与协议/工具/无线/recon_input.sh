#!/bin/bash
# 确认内核有没有 INPUT/HID 子系统（决定"插键鼠/触摸屏"这条路通不通）
echo "=== /dev/input 目录存在吗 ==="
ls -ld /dev/input 2>&1
echo
echo "=== /sys/class/input ==="
ls /sys/class/input 2>&1
echo
echo "=== 内核模块里有没有 input/hid ==="
ls /sys/module 2>/dev/null | grep -iE "^hid|^usbhid|^input|^evdev" || echo "  (一个都没有)"
echo
echo "=== /proc/config.gz 里的相关配置 ==="
if [ -f /proc/config.gz ]; then
  zcat /proc/config.gz | grep -E "CONFIG_INPUT=|CONFIG_INPUT_EVDEV=|CONFIG_HID=|CONFIG_USB_HID=|CONFIG_INPUT_KEYBOARD=|CONFIG_INPUT_MOUSE="
else
  echo "  (无 /proc/config.gz)"
fi
echo
echo "=== 内核版本 ==="
uname -a
echo
echo "=== /boot 内容 ==="
ls /boot 2>/dev/null | head
echo
echo "=== 设备节点 ==="
ls -l /dev/event* /dev/input/* 2>&1 | head
echo
echo "=== 可加载模块里有没有现成的 hid/input ==="
find /lib/modules -name "*hid*" -o -name "*evdev*" -o -name "*input*" 2>/dev/null | head -15
echo
echo "=== 串口设备（现在唯一可用的输入通道）==="
ls -l /dev/ttyUSB* /dev/ttyS* /dev/ttyAMA* 2>/dev/null | head
echo RECON_INPUT_DONE
