#!/usr/bin/env bash
# ============================================================================
# flash_and_test.sh —— 把 V9 位流加载到板子并点亮 DWE2100 屏
#
# ⚠️ 前提：**HDMI 线必须已经从电脑拔下来、插到板子的 HDMI 口上**。
#    屏是 DWE2100（原生 1024x600），板子输出的 raster 必须与它匹配。
#
# 用法： bash flash_and_test.sh [TAG] [--pattern bars|white|black|red]
# ============================================================================
set -u
TAG="${1:-v9}"
PATTERN="${3:-bars}"
SSH="ssh -i $HOME/.ssh/id_board -o BatchMode=yes -o StrictHostKeyChecking=no root@192.168.1.2"
FW="rans_hdmi_${TAG}.bin"

echo "=============================================================="
echo "  加载位流 $FW 并点亮 HDMI"
echo "=============================================================="

echo "== [1] 加载前状态 =="
$SSH "cat /sys/class/fpga_manager/fpga0/state; printf '  0x400C0084 = '; busybox devmem 0x400C0084"

echo "== [2] 热加载 $FW =="
$SSH "echo $FW > /sys/class/fpga_manager/fpga0/firmware && echo '  已写入'; sleep 3; cat /sys/class/fpga_manager/fpga0/state"

echo "== [3] 读 PL 指纹（0x20260922 = 我们的 rans_top，说明 rANS 编码器在位）=="
$SSH "printf '  0x400C0084 (rans RFU_R0) = '; busybox devmem 0x400C0084; printf '  0x400C00C0 (VERSION)      = '; busybox devmem 0x400C00C0"

echo "== [4] 写测试图并打开显示通路 =="
$SSH "cd /root && python3 -u hdmi-show-1024x600.py --pattern $PATTERN 2>&1 | tail -8"

echo "== [5] 回读显示寄存器 =="
$SSH 'for a in 0x40080018 0x40080050 0x40080054 0x4008006C 0x400800B4; do
  printf "  %s = %s\n" "$a" "$(busybox devmem $a)"
done'

echo
echo "=============================================================="
echo "  ★ 请看屏：应该出现 8 条彩色竖条（白/黄/青/绿/紫/红/蓝/深灰）"
echo "    若仍是花屏或黑屏，按顺序排查："
echo "      ① 屏的 HDMI 线是否已插到板子（不是电脑）"
echo "      ② 0x400800B4 是否 = 1（VTC 使能）、0x40080018 是否 = 1（HDMI 显示使能）"
echo "      ③ 0x40080054 是否指向一个合理地址（udma 保留区 0x2FDED000-0x3FFFFFFF 内）"
echo "      ④ 位流是否为 V9（含 1024x600 raster），而非 V8 的 1280x800"
echo "=============================================================="
