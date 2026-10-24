#!/bin/bash
# Build + verify the board-program template (no Icraft involved).
set -e
R=/mnt/e/fudanwei/GLC-共享包/开发板程序模板

echo "=== make available? ==="
if command -v make >/dev/null 2>&1; then make --version | head -1; else
  echo "  make MISSING -> apt-get install -y make"; apt-get install -y -q make >/dev/null 2>&1; make --version | head -1
fi
echo

for p in hello bench; do
  echo "################ $p ################"
  cd "$R/$p"
  # Makefile 对行尾极敏感：CRLF 会报 "missing separator"。先修掉。
  sed -i 's/\r$//' Makefile

  echo "--- make (aarch64) ---"
  make -s clean >/dev/null 2>&1 || true
  make
  echo

  echo "--- file ---"
  make -s file
  echo

  echo "--- run under qemu (aarch64) ---"
  make -s run-arm
  echo

  echo "--- 对照：本机 x86_64 同源码 ---"
  make -s ARCH=x86
  make -s run-x86
  echo
done

echo "################ 顶层清单 ################"
cd "$R"
find . -type f | sort
