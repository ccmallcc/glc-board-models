#!/bin/bash
# sample_regs.sh —— 每 2 s 采一次显示寄存器，看熄屏/唤醒时它们真的在变
#   0x40080018 HDMI 显示使能   （熄屏=0 / 唤醒=1）
#   0x400800B4 VTC 使能
#   0x40080054 显示帧地址（物理地址>>3）
for i in $(seq 1 16); do
  printf "  t=%2ds  0x18=%s  0xB4=%s  0x54=%s\n" $((i * 2)) \
    "$(busybox devmem 0x40080018 32 2>/dev/null)" \
    "$(busybox devmem 0x400800B4 32 2>/dev/null)" \
    "$(busybox devmem 0x40080054 32 2>/dev/null)"
  sleep 2
done
