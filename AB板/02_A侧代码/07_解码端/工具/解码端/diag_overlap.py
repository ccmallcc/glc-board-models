#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""diag_overlap.py —— 证明「多个 session 的物理地址互相重叠」

已实测（diag_budget.py）：s2/s3p1/s4 的 WEIGHT 逻辑地址**全都从 0x00001000 开始**。
若物理地址也各自从头分配，则后 apply 的网络会直接覆盖先 apply 的权重 —— 这正是
「s4_first 里 s3 输出爆炸、small_first 里 s4 输出 inf」的根因（而不是 2 GB 不够：
五个网络逻辑合计只有 ~563 MB）。

本脚本：依次 apply s2 和 s3p1（不做任何用户内存配置），打印两者 phy_segment 的
地址区间，检测重叠。
"""
import sys

sys.path.insert(0, '/root/glc')
sys.path.insert(0, '/root/tp5603_drv/glcdec')

import decode_board_bf16 as D                                    # noqa: E402
from icraft import xir, xrt, host_backend                        # noqa: E402
from icraft.zg330backend import ZG330Backend, OcmOpt             # noqa: E402

DEV_URL = 'axi://zg330aiu?npu=0x40000000&dma=0x80000000'


def segs(be):
    out = []
    try:
        for st, ps in be.phy_segment_map.items():
            a = int(ps.phy_addr)
            b = int(ps.byte_size)
            out.append((str(st), a, b))
    except Exception as e:                                        # noqa: BLE001
        print('   phy_segment_map ✗', str(e)[:200])
    return out


def overlap(x, y):
    (_, a1, s1), (_, a2, s2) = x, y
    return not (a1 + s1 <= a2 or a2 + s2 <= a1)


dev = xrt.Device.Open(DEV_URL)
print('defaultMemRegion type =', dev.defaultMemRegion().type_key)
try:
    mm = dev.defaultMemRegion().memManager()
    print('已有 memchunk 数 =', len(mm.getAllMemChunk()))
except Exception as e:                                            # noqa: BLE001
    print('memManager ✗', str(e)[:200])

loaded = []
for key in ('s2', 's3p1'):
    base, shapes, vids = D.SUB[key]
    net = xir.Network.CreateFromJsonFile(base + '.json')
    net.lazyLoadParamsFromFile(base + '.raw')
    nv = net.view(0).setOutputsOrderByValueIds(list(vids))
    sess = xrt.Session.Create([ZG330Backend, host_backend.HostBackend], nv,
                              [dev, xrt.HostDevice.Default()])
    be = ZG330Backend(sess.backends[0])
    be.ocmOptimize(OcmOpt.OPTION1)
    sess.apply()
    s = segs(be)
    loaded.append((key, s))
    print('\n%s 物理分段（apply 之后）:' % key)
    for name, a, b in s:
        print('    %-18s phy=0x%08x  size=%10d (%.1f MB)  区间 [0x%08x, 0x%08x)'
              % (name, a, b, b / 1048576.0, a, a + b))

    try:
        mm = dev.defaultMemRegion().memManager()
        allc = mm.getAllMemChunk()
        print('   设备 memchunk 总数 = %d' % len(allc))
        for c in allc[:8]:
            print('      chunk base=0x%08x size=%.1f MB'
                  % (int(c.begin.addr()), int(c.byte_size) / 1048576.0))
    except Exception as e:                                        # noqa: BLE001
        print('   memManager ✗', str(e)[:150])

if len(loaded) == 2:
    a, b = loaded[0][1], loaded[1][1]
    print('\n' + '=' * 76)
    print('  重叠检测 %s vs %s' % (loaded[0][0], loaded[1][0]))
    print('=' * 76)
    hit = 0
    for x in a:
        for y in b:
            if overlap(x, y):
                hit += 1
                print('  ✗ 重叠: %s[0x%08x,+%d)  ∩  %s[0x%08x,+%d)'
                      % (x[0], x[1], x[2], y[0], y[1], y[2]))
    if not hit:
        print('  ✓ 无重叠 —— 那就不是地址冲突，得另找原因')
print('DIAG_OVERLAP_DONE')
