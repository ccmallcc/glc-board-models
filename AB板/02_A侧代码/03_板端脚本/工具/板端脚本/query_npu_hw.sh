#!/bin/bash
# 确认 NPU 真的可访问：查硬件参数 + 试建 Session
PASS=fmsh
SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
$SSH root@192.168.0.2 'bash -s' <<'REMOTE'
set +e
P=/usr/local/lib/python3.8/dist-packages/icraft

echo "########## A. Session 怎么建（读存根）##########"
sed -n '708,760p' $P/xrt.pyi
echo

echo "########## B. 查 ZG330 硬件参数 ##########"
timeout 40 python3 - <<'PY'
from icraft import xrt
d = xrt.ZG330Device()
print("  ZG330Device 实例化 : OK")
for m in ('getRowsCols','layerCount'):
    try:
        print("  d.%s() = %r" % (m, getattr(d, m)()))
    except Exception as e:
        print("  d.%s() ERR %s: %s" % (m, type(e).__name__, str(e)[:110]))
try:
    d.setIcoreClkFreq(1000000000)
    print("  setIcoreClkFreq(1GHz) : OK")
except Exception as e:
    print("  setIcoreClkFreq ERR %s: %s" % (type(e).__name__, str(e)[:110]))
PY
echo "  (exit=$?)"
echo

echo "########## C. 试建 Session ##########"
timeout 60 python3 - <<'PY'
import inspect
from icraft import xrt
print("Session members:", [a for a in dir(xrt.Session) if not a.startswith('_')])
try:
    print("Session.__init__ doc:", (xrt.Session.__init__.__doc__ or '')[:300])
except Exception as e:
    print("  doc ERR:", e)
# 试探几种建法
for expr in ('xrt.Session()', 'xrt.Session(xrt.ZG330Device())'):
    try:
        s = eval(expr); print("  OK   %-34s -> %r" % (expr, s))
    except Exception as e:
        print("  ERR  %-34s %s: %s" % (expr, type(e).__name__, str(e)[:120]))
PY
echo "  (exit=$?)"
echo

echo "########## D. 有没有现成的 python 示例 / 文档 ##########"
dpkg -L icraft 2>/dev/null | grep -i -E '\.py$|example|sample|doc|README' | head -20
find /usr/share /usr/local/share -maxdepth 4 -iname '*icraft*' 2>/dev/null | head -10
REMOTE
