#!/bin/bash
# 对比：常驻引擎「并行载入」vs「串行载入」
cd /root/glc || exit 1
cat > /tmp/eng_time.py <<'PY'
import os, sys, time
sys.path.insert(0, "/root/glc")
import glc_rsd_fast as R
t = time.time()
e = R.Engine("/root/glc/models", verbose=True)
dt = time.time() - t
print("### SETUP_TOTAL %.3f s  (GLC_RSD_PARALLEL=%s)" % (dt, os.environ.get("GLC_RSD_PARALLEL", "1")))
PY
echo "######## 并行（默认）########"
S=$(date +%s); GLC_RSD_PARALLEL=1 GLC_RSD_RESET=each python3 -u /tmp/eng_time.py 2>&1 | grep -E "Engine\(fast\)|SETUP_TOTAL|!!" ; E=$(date +%s)
echo "  进程墙钟 $((E-S)) s"
echo
echo "######## 串行（对照）########"
S=$(date +%s); GLC_RSD_PARALLEL=0 GLC_RSD_RESET=each python3 -u /tmp/eng_time.py 2>&1 | grep -E "Engine\(fast\)|SETUP_TOTAL|!!" ; E=$(date +%s)
echo "  进程墙钟 $((E-S)) s"
echo ENG_TIME_DONE
