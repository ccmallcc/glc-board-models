#!/bin/bash
# Does the official CMake + find_package path work in FPAI-Ubuntu2004?
set -e
P=/mnt/e/fudanwei/_logs/xcmake
cd "$P"
rm -rf build

echo "=== cmake configure (plain, as the official BUILD_GUIDE says) ==="
if cmake -S . -B build -DCMAKE_BUILD_TYPE=Release 2>&1 | tail -20; then
  echo "CONFIGURE OK"
else
  echo "CONFIGURE FAILED -- retry with CMAKE_PREFIX_PATH=/usr/cmake"
  rm -rf build
  cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH=/usr/cmake 2>&1 | tail -15
fi
echo

echo "=== build ==="
cmake --build build -j"$(nproc)" 2>&1 | tail -15
echo

echo "=== file ==="
file build/demo
echo
echo "=== NEEDED libs (are the aarch64 Icraft .so resolved?) ==="
aarch64-linux-gnu-readelf -d build/demo | grep -E 'NEEDED|RUNPATH|RPATH'
echo
echo "=== run it on this machine (qemu) to prove it is a working aarch64 binary ==="
qemu-aarch64-static -L /usr/aarch64-linux-gnu build/demo || echo "(qemu run failed)"
