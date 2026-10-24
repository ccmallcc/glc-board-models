#!/bin/bash
# Cross-compile the board-side (aarch64) binaries from the x86_64 WSL distro.
# Script lives on an ASCII path on purpose: passing a Chinese path as an
# argument through PowerShell -> wsl.exe mangles it, but a path INSIDE a
# UTF-8 script file is read correctly by bash.
set -e
SRC=/mnt/e/fudanwei/工作区/rans
OUT=/tmp/xbuild
rm -rf "$OUT"; mkdir -p "$OUT"; cd "$OUT"

echo "=== toolchain ==="
aarch64-linux-gnu-g++ --version | head -1
echo

echo "=== 1) rans_port.cpp (self-contained rANS core) ==="
aarch64-linux-gnu-g++ -O2 -std=c++11 -o rans_port_arm64 "$SRC/rans_port.cpp"
echo "  ok"
echo

echo "=== 2) glc2_pack.cpp (container packer, needs glc_cdf_table.h) ==="
aarch64-linux-gnu-g++ -O2 -std=c++11 -I"$SRC" -o glc2_pack_arm64 "$SRC/glc2_pack.cpp"
echo "  ok"
echo

echo "=== 3) rans_board.cpp (V2 board-path regression harness) ==="
aarch64-linux-gnu-g++ -O2 -std=c++11 -o rans_board_arm64 "$SRC/rans_board.cpp"
echo "  ok"
echo

echo "=== file(1) ==="
file rans_port_arm64 glc2_pack_arm64 rans_board_arm64
echo

echo "=== sizes ==="
ls -l rans_port_arm64 glc2_pack_arm64 rans_board_arm64
echo

echo "=== dynamic deps (aarch64) ==="
aarch64-linux-gnu-readelf -d rans_port_arm64 | grep -E 'NEEDED|interpreter' || true
echo

echo "=== qemu available? ==="
command -v qemu-aarch64-static || command -v qemu-aarch64 || echo "NO qemu -> cannot execute aarch64 here (expected)"
