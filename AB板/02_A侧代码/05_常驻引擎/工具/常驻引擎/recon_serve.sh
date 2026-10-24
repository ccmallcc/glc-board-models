#!/bin/sh
# GLC 2026-10-08: 摸清 icraft-serve 与 xrt.Session（常驻进程的两条路）
echo "=== icraft-serve --help ==="
icraft-serve --help 2>&1 | head -70
echo
echo "=== icraft-serve -h ==="
icraft-serve -h 2>&1 | head -40
echo
echo "=== icraft --help ==="
icraft --help 2>&1 | head -40
echo
echo "=== xrt.Session 的方法与签名 ==="
python3 -c "
from icraft import xrt
print('Session attrs:', [n for n in dir(xrt.Session) if not n.startswith('_')])
for n in dir(xrt.Session):
    if n.startswith('_'): continue
    try:
        o = getattr(xrt.Session, n)
        d = getattr(o, '__doc__', None)
        print('  %-24s %s' % (n, (d or '').strip().replace(chr(10),' ')[:110]))
    except Exception as e:
        print('  %-24s <err %s>' % (n, e))
" 2>&1
echo
echo "=== xrt.Tensor 的方法 ==="
python3 -c "
from icraft import xrt
print([n for n in dir(xrt.Tensor) if not n.startswith('_')])
" 2>&1
echo
echo "=== xrt.Backend ==="
python3 -c "
from icraft import xrt
print([n for n in dir(xrt.Backend) if not n.startswith('_')])
" 2>&1
echo
echo "=== icraft python 包内容 ==="
ls -l /usr/local/lib/python3.8/dist-packages/icraft/ 2>/dev/null
echo "RECON_SERVE_DONE"
