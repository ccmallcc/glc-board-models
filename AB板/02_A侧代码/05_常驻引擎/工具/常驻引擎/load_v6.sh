#!/bin/bash
# GLC 2026-10-09: 装回 v6 位流（rANS），验指纹
echo "=== 装前 ==="
echo -n "  +0x84 = "; busybox devmem 0x400C0084 32
echo -n "  state = "; cat /sys/class/fpga_manager/fpga0/state
echo
echo "=== 加载 v6.bin ==="
ls -l /lib/firmware/v6.bin
echo v6.bin > /sys/class/fpga_manager/fpga0/firmware
sleep 4
echo "=== 装后 ==="
echo -n "  +0x84 = "; busybox devmem 0x400C0084 32
echo -n "  +0xC0 = "; busybox devmem 0x400C00C0 32
echo -n "  state = "; cat /sys/class/fpga_manager/fpga0/state
echo "  （期望 +0x84 = 0x20260922）"
echo LOAD_V6_DONE
