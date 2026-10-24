#!/bin/bash
# 装板端 runtime（3.36.1）并重试 Python 调 NPU
PASS=fmsh
SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
$SSH root@192.168.0.2 'bash -s' <<'REMOTE'
set +e
cd /home/work

echo "########## A. deb 里有没有 python 部分 ##########"
dpkg-deb -c Icraft_3.36.1_onchip.deb | grep -i -E '\.py|dist-packages|site-packages|\.whl' | head -10 || echo "  (deb 里没有 python 文件)"
echo "--- deb 里的 .so ---"
dpkg-deb -c Icraft_3.36.1_onchip.deb | grep '\.so' | awk '{print "  "$6, $3}'
echo

echo "########## B. 安装 ##########"
dpkg -i Icraft_3.36.1_onchip.deb CustomOp_3.36.1_onchip.deb 2>&1 | tail -15
echo "exit=$?"
ldconfig
echo
echo "--- 确认 ---"
dpkg -l | grep -i -E 'icraft|customop'
ls /usr/lib/aarch64-linux-gnu/ | grep -i -E 'icraft|customop'
echo

echo "########## C. 重试 import ##########"
python3 - <<'PY'
for sub in ('xir','xrt','zg330backend','buyibackend','host_backend'):
    try:
        m = __import__('icraft.'+sub, fromlist=['*'])
        print("  icraft.%-14s OK" % sub)
    except Exception as e:
        print("  icraft.%-14s FAIL %s: %s" % (sub, type(e).__name__, str(e)[:110]))
PY
echo

echo "########## D. Python 绑定版本 vs 库版本 ##########"
python3 -c "import icraft,os;print('python pkg dir:',os.path.dirname(icraft.__file__))"
dpkg -l | awk '/icraft|Icraft|CustomOp/{print "  deb:",$2,$3}'
find /usr/local/lib/python3.8/dist-packages -maxdepth 1 -iname '*icraft*' -printf '  pip: %f\n' 2>/dev/null
echo

echo "########## E. 试开 NPU 设备 ##########"
python3 - <<'PY'
import traceback
try:
    from icraft import xrt
    print("xrt attrs:", [a for a in dir(xrt) if not a.startswith('_')][:40])
except Exception as e:
    print("xrt import FAIL:", e); traceback.print_exc(); raise SystemExit(0)
for expr in ('xrt.Device("ZG330")','xrt.ZG330Device()','xrt.Device()','xrt.get_device("ZG330")'):
    try:
        d = eval(expr); print("  OK  %-24s -> %r" % (expr, d))
    except Exception as e:
        print("  ERR %-24s %s: %s" % (expr, type(e).__name__, str(e)[:100]))
PY
REMOTE
