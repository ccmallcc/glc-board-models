#!/bin/bash
# 在 B（解码）板上编译 rANS C 加速库（A 侧 2026-10-12）
# 用法： bash build_rans_fast.sh
set -e
D=/root/tp5603_drv/glcdec
cd "$D"
echo "== gcc =="; gcc --version | head -1
echo "== 编译 =="
gcc -O2 -fPIC -shared -Wall -o "$D/rans_fast.so" "$D/rans_fast.c"
ls -la "$D/rans_fast.so"
echo "== 自检（能否 dlopen）=="
python3 - <<'PY'
import ctypes, os
p = '/root/tp5603_drv/glcdec/rans_fast.so'
lib = ctypes.CDLL(p)
lib.rans_fast_version.restype = ctypes.c_char_p
print('OK:', lib.rans_fast_version().decode())
PY
echo BUILD_RANS_FAST_DONE
