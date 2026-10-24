#!/bin/bash
# 把 pip 的 icraft 从 3.33.1 升到 3.36.1（用 /home/work 里现成的 wheel），再试 import
PASS=fmsh
SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
$SSH root@192.168.0.2 'bash -s' <<'REMOTE'
set +e
cd /home/work

echo "########## A. 卸掉旧的 3.33.1 ##########"
python3 -m pip uninstall -y icraft 2>&1 | tail -3
rm -rf /usr/local/lib/python3.8/dist-packages/icraft /usr/local/lib/python3.8/dist-packages/icraft-3.33.1.dist-info
echo

echo "########## B. 装 3.36.1 wheel（本地，不联网）##########"
python3 -m pip install --no-index --no-deps --force-reinstall \
  /home/work/icraft-3.36.1-cp38-none-manylinux2014_aarch64.whl 2>&1 | tail -8
echo

echo "########## C. 装到哪了 ##########"
python3 -c "import icraft,os;print('  ',icraft.__file__)" 2>&1
python3 -m pip show icraft 2>/dev/null | head -4
find / -xdev -maxdepth 6 -name 'xrt.cpython-38-aarch64-linux-gnu.so' 2>/dev/null
echo

echo "########## D. 重试 import ##########"
python3 - <<'PY'
for sub in ('xir','xrt','zg330backend','buyibackend','host_backend'):
    try:
        __import__('icraft.'+sub, fromlist=['*']); print("  icraft.%-14s OK" % sub)
    except Exception as e:
        print("  icraft.%-14s FAIL %s: %s" % (sub, type(e).__name__, str(e)[:120]))
PY
echo

echo "########## E. API 长什么样（从 .pyi 存根读）##########"
P=$(python3 -c "import icraft,os;print(os.path.dirname(icraft.__file__))" 2>/dev/null)
echo "package dir: $P"
ls "$P" 2>/dev/null
echo "--- xrt.pyi 里的 class ---"
grep -n '^class \|^def ' "$P/xrt.pyi" 2>/dev/null | head -30
echo "--- zg330backend.pyi 里的 class ---"
grep -n '^class \|^def ' "$P/zg330backend.pyi" 2>/dev/null | head -30
REMOTE
