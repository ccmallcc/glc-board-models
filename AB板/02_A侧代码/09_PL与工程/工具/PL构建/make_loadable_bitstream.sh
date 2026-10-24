#!/usr/bin/env bash
# ============================================================================
# make_loadable_bitstream.sh —— 把 Vivado 产物做成板子能热加载的 .bin
#
# 完整链路（每一步都在本文件里，可复现）：
#   1) Vivado V9 构建  ->  fpai_demo_vivado.runs/impl_1/ai7030_edif_top.bit
#   2) Procise 打补丁  ->  *_disable_icap.bit   （关掉 ICAP，否则 fpga_manager
#                          热加载会失败；官方补丁同时打 VCCM，PatchID=32494）
#   3) bit2bin.py      ->  *.bin   （剥掉 149 字节 .bit 头；已验证：
#                          头 149 + 位流 5,980,460 = 5,980,609，与板上 .bin 逐字节同尺寸）
#   4) scp 到板子 /lib/firmware/
#
# 用法： bash make_loadable_bitstream.sh [TAG]
# ============================================================================
set -u
TAG="${1:-v9}"
RB=/e/pl_work/rans_board
PROJ=/e/pl_work/fpai_demo/fpai_demo_fpga
BIT="$PROJ/fpai_demo_vivado.runs/impl_1/ai7030_edif_top.bit"
PATCHED="$PROJ/fpai_demo_vivado.runs/impl_1/ai7030_edif_top_disable_icap.bit"
OUT="$RB/rans_hdmi_${TAG}"
SSH="ssh -i $HOME/.ssh/id_board -o BatchMode=yes -o StrictHostKeyChecking=no root@192.168.1.2"

echo "=============================================================="
echo "  TAG=$TAG"
echo "=============================================================="

echo "== [1/4] 找 Vivado 产物 =="
if [ ! -f "$BIT" ]; then
    echo "  ✗ 没有 $BIT —— 构建还没跑完？"
    exit 1
fi
ls -la "$BIT"

echo "== [2/4] Procise 打 disable_icap 补丁 =="
cat > "$PROJ/procise_run_disable_icap_${TAG}.tcl" <<EOF
set_device JFMQL30TAI676H
increment_bit_cfg_v3  $BIT $PATCHED -disable_icap
EOF
cat > "$PROJ/call_procise_disable_icap_${TAG}.bat" <<EOF
@set PROCISE_DIR=E:/fudanwei/Procise
@set TCL_LIBRARY=%PROCISE_DIR%/tcl8.4
@set PATH=%PROCISE_DIR%/dll;%PROCISE_DIR%/bin;%PATH%
@set ICTIME_HOME=%PROCISE_DIR%
@set APP_DIR=%PROCISE_DIR%
@set FMSH_DB=%PROCISE_DIR%/db
@procise.exe $PROJ/procise_run_disable_icap_${TAG}.tcl
EOF
cmd.exe /c "$(cygpath -w "$PROJ/call_procise_disable_icap_${TAG}.bat")" 2>&1 | tail -5
if [ ! -f "$PATCHED" ]; then echo "  ✗ Procise 没产出 $PATCHED"; exit 1; fi
ls -la "$PATCHED"

echo "== [3/4] .bit -> .bin =="
python "/e/fudanwei/工作区/hdmi/bit2bin.py" "$PATCHED" "${OUT}.bin"
ls -la "${OUT}.bin"

echo "== [4/4] 拷到板子 /lib/firmware/ =="
$SSH "cat > /lib/firmware/rans_hdmi_${TAG}.bin" < "${OUT}.bin"
$SSH "ls -la /lib/firmware/rans_hdmi_${TAG}.bin; md5sum /lib/firmware/rans_hdmi_${TAG}.bin"
md5sum "${OUT}.bin"

echo
echo "=============================================================="
echo "  完成。上板加载："
echo "    echo rans_hdmi_${TAG}.bin > /sys/class/fpga_manager/fpga0/firmware"
echo "=============================================================="
