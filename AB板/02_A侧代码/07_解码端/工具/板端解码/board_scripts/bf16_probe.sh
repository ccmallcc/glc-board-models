#!/bin/bash
# isolate bf16 s4: build the y_hat input, run it with ZG330 and with Host
set -u
P=/root/bf16probe
rm -rf $P; mkdir -p $P
cd $P

python3 - <<'PY'
import sys, numpy as np
sys.path.insert(0, '/root/glcdec')
from decode_board import to_nhwc
d = np.load('/root/dec_out/int8base_p1.npz')
y = d['y_hat']
print('y_hat(NCHW)', y.shape, 'range', float(y.min()), float(y.max()))
to_nhwc(np.ascontiguousarray(y, dtype=np.float32)).tofile('/root/bf16probe/y_hat.ftmp')
PY
ls -l $P/y_hat.ftmp

B=/root/glc/models/s4_bf16/s4_gs_generator_ZG
IC=/usr/bin/icraft-run

echo "=============================================================="
echo "### A) ZG330 backend (NPU)"
echo "=============================================================="
$IC --json $B.json --raw $B.raw --input $P/y_hat.ftmp \
    --backends 'ZG330,axi://zg330aiu;Host' --log_path $P/log_zg \
    --dump_format SFB --dump_ftmp 4107 > $P/zg.log 2>&1
echo "rc=$?"
echo "--- key lines ---"
grep -n -i "sync failed\|exception\|error\|layer_count\|alloc\|memory\|dma\|size\|fail" $P/zg.log | head -40
echo "--- dump produced? ---"
find $P/log_zg -name '*.ftmp' 2>/dev/null | head

echo
echo "=============================================================="
echo "### B) Host backend (no NPU) -- is the model itself valid?"
echo "=============================================================="
$IC --json $B.json --raw $B.raw --input $P/y_hat.ftmp \
    --backends Host --log_path $P/log_host \
    --dump_format SFB --dump_ftmp 4107 > $P/host.log 2>&1
echo "rc=$?"
find $P/log_host -name '*.ftmp' 2>/dev/null | head
echo "--- tail ---"
tail -12 $P/host.log
echo BF16_PROBE_DONE
