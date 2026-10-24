#!/bin/bash
# Simulate "the bundle landed on the board" and run its scripts.
set -e
T=/tmp/bundletest
rm -rf "$T"; mkdir -p "$T"
cp -r "/mnt/e/fudanwei/开发板传输包" "$T/pkg"
cd "$T/pkg"
sed -i 's/\r$//' */*.sh
chmod +x 1_hello/hello_arm64 2_bench/bench_arm64 3_rANS内核/rans_port 4_板端回归/rans_board

echo "### binfmt 透明执行 aarch64（装了 qemu-user-static 后应可直接 ./x）###"
./1_hello/hello_arm64
echo

echo "### 3_rANS内核/run.sh ###"
cd 3_rANS内核 && bash run.sh 2>&1 | tail -12; cd ..
echo

echo "### 4_板端回归/run.sh ###"
cd 4_板端回归 && bash run.sh 2>&1; cd ..
