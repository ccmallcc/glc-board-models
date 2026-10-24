#!/bin/bash
# Prove the CRLF-in-Makefile claim instead of asserting it.
set -e
T=/tmp/crlftest
rm -rf "$T"; mkdir -p "$T"
cp /mnt/e/fudanwei/GLC-共享包/开发板程序模板/hello/main.cpp "$T"/
cp /mnt/e/fudanwei/GLC-共享包/开发板程序模板/hello/Makefile "$T"/
cd "$T"

echo "=== A. LF Makefile (normal) ==="
sed -i 's/\r$//' Makefile
make -s ARCH=x86 2>&1 | head -3 && echo "  -> OK" || echo "  -> FAILED"
echo

echo "=== B. same Makefile with CRLF (what a Windows editor does) ==="
sed -i 's/$/\r/' Makefile
file Makefile
make -s clean >/dev/null 2>&1 || true
set +e
out=$(make ARCH=x86 2>&1); rc=$?
set -e
echo "$out" | head -5
echo "  exit=$rc"
echo

echo "=== C. does CRLF hurt the .cpp too? ==="
sed -i 's/$/\r/' main.cpp
file main.cpp
sed -i 's/\r$//' Makefile
set +e
out2=$(make -s ARCH=x86 2>&1); rc2=$?
set -e
echo "  make exit=$rc2  $( [ $rc2 -eq 0 ] && echo '-> .cpp 有 CRLF 不影响编译' || echo '-> 也挂了')"
