#!/bin/sh
# GLC 2026-10-08: 摸清板端 ICraft 的可用接口（为"常驻进程"做准备）
echo "=== /usr/bin 下的 icraft 系列 ==="
ls -l /usr/bin/icraft* /usr/local/bin/icraft* 2>/dev/null
echo
echo "=== icraft-run --help ==="
icraft-run --help 2>&1 | head -60
echo
echo "=== icraft-run -h ==="
icraft-run -h 2>&1 | head -40
echo
echo "=== 其它 icraft 可执行 ==="
ls /usr/bin | grep -i -E 'icraft|xrt|npu|zg' 2>/dev/null
echo
echo "=== python icraft 模块 ==="
python3 -c "import icraft, os; print('icraft at', os.path.dirname(icraft.__file__)); print([n for n in dir(icraft) if not n.startswith('_')])" 2>&1
echo
echo "=== python icraft.xrt 模块 ==="
python3 -c "from icraft import xrt; print([n for n in dir(xrt) if not n.startswith('_')])" 2>&1
echo
echo "=== xrt.Device 的方法 ==="
python3 -c "
from icraft import xrt
d=[n for n in dir(xrt.Device) if not n.startswith('_')]
print(d)
" 2>&1
echo
echo "=== 库文件 ==="
ls -l /usr/lib/libicraft* /usr/lib/aarch64-linux-gnu/libicraft* 2>/dev/null | head
echo "RECON_ICRAFT_DONE"
