#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""diag_budget.py —— 单个子图 apply() 之后到底占多少 PL DDR（物理分段实测）

动机：PL DDR 只有 2 GB。s4 单独跑「Network size:3431640960 beyond 2GB」却仍然正确，
说明那只是**优化前**的估算，ETM 会把它压下来。只要拿到每个子图 apply() 后的
**真实物理分段字节数**，就能算出 5 个 session 能不能共存、差多少。

用法：python3 diag_budget.py <s2|s3p1|s4|...>
"""
import sys
import time

sys.path.insert(0, '/root/glc')
sys.path.insert(0, '/root/tp5603_drv/glcdec')

import decode_board_bf16 as D                        # noqa: E402
from icraft import xir, xrt, host_backend            # noqa: E402
from icraft.zg330backend import ZG330Backend, OcmOpt # noqa: E402

DEV_URL = 'axi://zg330aiu?npu=0x40000000&dma=0x80000000'

key = sys.argv[1]
base, shapes, vids = D.SUB[key]
print('=' * 80)
print('  子图 %s   json=%s.raw' % (key, base))
print('=' * 80)

dev = xrt.Device.Open(DEV_URL)
t0 = time.time()
net = xir.Network.CreateFromJsonFile(base + '.json')
net.lazyLoadParamsFromFile(base + '.raw')
nv = net.view(0).setOutputsOrderByValueIds(list(vids))
sess = xrt.Session.Create([ZG330Backend, host_backend.HostBackend], nv,
                          [dev, xrt.HostDevice.Default()])
be = ZG330Backend(sess.backends[0])
be.ocmOptimize(OcmOpt.OPTION1)
sess.enableTimeProfile(True)
t1 = time.time()
sess.apply()
print('  载入 %.2f s + apply %.2f s' % (t1 - t0, time.time() - t1), flush=True)

try:
    print('  precheck() =', be.precheck())
except Exception as e:                                # noqa: BLE001
    print('  precheck 失败:', e)

print('  --- phy_segment_map（真实物理分段）---', flush=True)
tot = 0
try:
    for seg, ps in be.phy_segment_map.items():
        bs = int(ps.byte_size)
        tot += bs
        print('    %-8s byte_size=%12d (%.1f MB)  phy_addr=0x%08x  user_used=%s'
              % (str(seg), bs, bs / 1048576.0, int(ps.phy_addr), ps.user_used), flush=True)
except Exception as e:                                # noqa: BLE001
    print('    ✗', e)
print('  ★ 合计 %.1f MB (%.4f GB)' % (tot / 1048576.0, tot / 1073741824.0))

print('  --- logic_segment_map（逻辑分段）---', flush=True)
tot2 = 0
try:
    for seg, ls in be.logic_segment_map.items():
        bs = int(ls.byte_size)
        tot2 += bs
        print('    %-8s byte_size=%12d (%.1f MB)  logic_addr=0x%08x'
              % (str(seg), bs, bs / 1048576.0, int(ls.logic_addr)), flush=True)
except Exception as e:                                # noqa: BLE001
    print('    ✗', e)
print('  ★ 逻辑合计 %.1f MB (%.4f GB)' % (tot2 / 1048576.0, tot2 / 1073741824.0))
print('DIAG_BUDGET_DONE')
