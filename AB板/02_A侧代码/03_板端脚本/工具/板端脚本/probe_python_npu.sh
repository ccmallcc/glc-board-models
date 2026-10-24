#!/bin/bash
# 探 icraft 的 Python API，并尝试打开 ZG330 设备。
PASS=fmsh
SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
$SSH root@192.168.0.2 'bash -s' <<'REMOTE'
echo "########## A. /home/work 完整清单 ##########"
ls -la /home/work/
echo
echo "--- 那个 9KB 的 hello_arm64 是什么 ---"
file /home/work/hello_arm64
md5sum /home/work/hello_arm64
/home/work/hello_arm64 2>&1 | head -5
echo

echo "########## B. icraft python 包结构 ##########"
ls -la /usr/local/lib/python3.8/dist-packages/icraft/
echo
echo "--- __init__.py ---"
cat /usr/local/lib/python3.8/dist-packages/icraft/__init__.py 2>/dev/null | head -40
echo

echo "########## C. 顶层 API ##########"
python3 - <<'PY'
import icraft, sys
print("icraft file :", icraft.__file__)
print("attrs       :", [a for a in dir(icraft) if not a.startswith('_')])
for a in ('__version__','version','VERSION'):
    if hasattr(icraft, a): print(a, "=", getattr(icraft, a))
print()
for sub in ('xir','xrt','zg330backend','buyibackend','host_backend'):
    try:
        m = __import__('icraft.'+sub, fromlist=['*'])
        print("import icraft.%-14s OK   attrs=%s" % (sub, [a for a in dir(m) if not a.startswith('_')][:18]))
    except Exception as e:
        print("import icraft.%-14s FAIL %s: %s" % (sub, type(e).__name__, e))
PY
echo

echo "########## D. xrt 里有什么（设备/运行器）##########"
python3 - <<'PY'
try:
    from icraft import xrt
    print([a for a in dir(xrt) if not a.startswith('_')])
except Exception as e:
    print("xrt FAIL:", e)
try:
    from icraft import xir
    print("xir:", [a for a in dir(xir) if not a.startswith('_')][:40])
except Exception as e:
    print("xir FAIL:", e)
PY
echo

echo "########## E. 试打开 ZG330 设备 ##########"
python3 - <<'PY'
import traceback
try:
    from icraft import xrt
    for name in ('Device','ZG330Device','DeviceNode','ZG330DeviceNode'):
        if hasattr(xrt, name):
            print("xrt.%s 存在" % name)
    # 常见入口试探
    for expr in ('xrt.Device("ZG330")', 'xrt.ZG330Device()', 'xrt.Device()'):
        try:
            d = eval(expr)
            print("OK  %s -> %r" % (expr, d))
        except Exception as e:
            print("ERR %-28s %s: %s" % (expr, type(e).__name__, str(e)[:120]))
except Exception:
    traceback.print_exc()
PY
REMOTE
