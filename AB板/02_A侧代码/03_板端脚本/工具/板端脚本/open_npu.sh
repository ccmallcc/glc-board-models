#!/bin/bash
# 真刀真枪：从 Python 打开 ZG330 NPU 设备
PASS=fmsh
SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
$SSH root@192.168.0.2 'bash -s' <<'REMOTE'
set +e
P=/usr/local/lib/python3.8/dist-packages/icraft

echo "########## A. ZG330Device 的创建方式（读存根）##########"
sed -n '1131,1200p' $P/xrt.pyi
echo
echo "########## B. Device 基类里和创建有关的静态方法 ##########"
grep -n 'staticmethod\|def create\|def open\|def init\|def get\|@classmethod' $P/xrt.pyi | sed -n '1,40p'
echo
echo "########## C. 试试创建 ZG330Device ##########"
python3 - <<'PY'
import traceback
from icraft import xrt
print("xrt attrs:", [a for a in dir(xrt) if not a.startswith('_')])
D = xrt.ZG330Device
print("ZG330Device members:", [a for a in dir(D) if not a.startswith('_')][:40])
print()
for expr in ('xrt.ZG330Device()',
             'xrt.Device()',
             'xrt.ZG330Device.create()',
             'xrt.Device.create("ZG330")',
             'xrt.Device.create()'):
    try:
        d = eval(expr); print("  OK   %-30s -> %r" % (expr, d))
    except Exception as e:
        print("  ERR  %-30s %s: %s" % (expr, type(e).__name__, str(e)[:130]))
PY
echo
echo "########## D. 打开 /dev/mem 之类的权限检查 ##########"
id
ls -l /dev/mem /dev/udmabuf0 2>/dev/null
echo "SELinux/AppArmor: $(cat /sys/kernel/security/lsm 2>/dev/null || echo 未知)"
REMOTE
