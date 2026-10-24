#!/bin/bash
# Simulate the bundle ON THE BOARD by shimming the aarch64 binaries through qemu.
# (WSL did NOT register binfmt_misc, so ./aarch64 -> "Exec format error".)
set -e
Q="qemu-aarch64-static -L /usr/aarch64-linux-gnu"
T=/tmp/bundletest
rm -rf "$T"; mkdir -p "$T"
cp -r "/mnt/e/fudanwei/开发板传输包" "$T/pkg"
cd "$T/pkg"
sed -i 's/\r$//' */*.sh

shim() {  # $1 = path to the aarch64 binary
  mv "$1" "$1.real"
  printf '#!/bin/bash\nexec %s "%s.real" "$@"\n' "$Q" "$PWD/$1" > "$1"
  chmod +x "$1" "$1.real"
}
shim 1_hello/hello_arm64
shim 2_bench/bench_arm64
shim 3_rANS内核/rans_port
shim 4_板端回归/rans_board

echo "### 1_hello ###"
./1_hello/hello_arm64
echo

echo "### 3_rANS内核/run.sh ###"
cd 3_rANS内核 && bash run.sh 2>&1 | tail -14; cd ..
echo

echo "### 4_板端回归/run.sh ###"
cd 4_板端回归 && bash run.sh 2>&1; cd ..
