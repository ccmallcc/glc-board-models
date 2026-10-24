#!/bin/bash
# Apples-to-apples: build the SAME source for x86_64 and aarch64 with the SAME
# compiler (FPAI-Ubuntu2004, g++ 9.4), then run both and compare byte-for-byte.
set -e
SRC=/mnt/e/fudanwei/工作区/rans
OUT=$SRC/board_bin
cd "$SRC"

echo "=== build x86_64 locally (glibc 2.31, g++ 9.4) ==="
g++ -O2 -std=c++11 -o /tmp/rans_board_x86 rans_board.cpp
echo "  ok"; echo

echo "############ vector-by-vector: aarch64(qemu) vs x86_64(native) ############"
printf '%-8s %-12s %-12s %-10s %s\n' VECTOR ARM64_OUT X86_OUT BYTES LOG
same=0; tot=0
for name in phase0 phase1 phase2 phase3 stress; do
  a=$(qemu-aarch64-static "$OUT/rans_board_arm64_static" "boardvec_$name.txt" glc_cdf_table.bin 2>&1) && ra=0 || ra=$?
  x=$(/tmp/rans_board_x86 "boardvec_$name.txt" glc_cdf_table.bin 2>&1) && rx=0 || rx=$?
  ab=$(echo "$a" | grep -o '板端输出 : [0-9]* bytes' | head -1)
  xb=$(echo "$x" | grep -o '板端输出 : [0-9]* bytes' | head -1)
  if [ "$a" = "$x" ] && [ $ra -eq 0 ] && [ $rx -eq 0 ]; then r="完全一致 ✅"; same=$((same+1)); else r="有差异 ❌"; fi
  tot=$((tot+1))
  printf '%-8s %-12s %-12s %-10s %s\n' "$name" "${ab#板端输出 : }" "${xb#板端输出 : }" "$r" ""
done
echo
echo "---- 输出逐字一致：$same / $tot"
echo

echo "=== V1 rANS core: rans_port, x86_64 vs aarch64 ==="
g++ -O2 -std=c++11 -o /tmp/rans_port_x86 rans_port.cpp
for v in phase0 stress; do
  printf '%-8s ' "$v"
  a=$(qemu-aarch64-static "$OUT/rans_port_arm64_static" "vector_$v.txt" 2>&1) && ra=0 || ra=$?
  x=$(/tmp/rans_port_x86 "vector_$v.txt" 2>&1) && rx=0 || rx=$?
  [ "$a" = "$x" ] && [ $ra -eq 0 ] && [ $rx -eq 0 ] && echo "一致 ✅  ($(echo "$x" | tail -1))" || echo "有差异 ❌"
done
