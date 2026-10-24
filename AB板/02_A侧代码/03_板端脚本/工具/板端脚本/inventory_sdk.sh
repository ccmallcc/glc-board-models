#!/bin/bash
# Inventory the aarch64 side of the Icraft SDK inside FPAI-Ubuntu2004.
echo "=== /usr/cmake (cmake package configs) ==="
ls /usr/cmake 2>/dev/null
echo
echo "=== aarch64 icraft libs ==="
ls /usr/lib/aarch64-linux-gnu/ 2>/dev/null | grep -i icraft
echo
echo "=== aarch64 npu-related libs ==="
ls /usr/lib/aarch64-linux-gnu/ 2>/dev/null | grep -E 'zg330|buyi|aiu|mock'
echo
echo "=== does a zg330backend cmake config exist? ==="
ls /usr/cmake/ | grep -i zg330 || echo "  (no file with 'zg330' in the name)"
echo
echo "=== content of one config (first 30 lines) ==="
f=$(ls /usr/cmake/*zg330* 2>/dev/null | head -1)
if [ -n "$f" ]; then echo "--- $f"; head -30 "$f"; else echo "none"; fi
echo
echo "=== headers ==="
ls /usr/include | grep -i -E 'icraft|xir' || echo "  (none in /usr/include)"
