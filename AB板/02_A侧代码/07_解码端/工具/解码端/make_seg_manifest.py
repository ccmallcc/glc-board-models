#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""make_seg_manifest.py —— 生成/迭代每个子图各物理段的**精确字节数**清单

为什么需要：
  ZG330Backend.userReuseSegment(memchunk, segment_type) 有两条硬校验（实测报错原文）：
    ① Check failed: (memchunk->begin.addr() % ETM_CHUNK_ALIGN == 0)
       → malloc chunk's begin addr is not align to 4096
    ② Exception info : segment byte_size and memchunk byte_size do not match!
  ⇒ 必须给「每个网络 × 每个段类型」单独 malloc 一个 **4096 对齐、大小精确相等** 的 chunk。

为什么还要「迭代」：
  段大小只有在 apply() 之后才知道；而且一旦把 WEIGHT/INSTR 钉到用户 chunk，
  ETM 会重算剩下的内存池 ⇒ FTMP 的目标大小会变（实测 s4：清单里 64 MB，
  钉完其它段后报 "segment byte_size and memchunk byte_size do not match"）。
  这是个不动点问题：用上一轮的实测值当下一轮的输入，迭代到稳定。

用法：
  python3 make_seg_manifest.py s2            # 第一轮：不钉，只量
  python3 make_seg_manifest.py s4 --use-seg  # 后续轮：按清单钉，量完写回
每个 key 必须**单独进程**跑（PL DDR 要进程退出才释放）。
输出：/root/glc/seg_manifest.json
"""
import json
import os
import sys
import time

sys.path.insert(0, '/root/glc')
sys.path.insert(0, '/root/tp5603_drv/glcdec')

import decode_board_bf16 as D                                    # noqa: E402
from icraft import xir, xrt, host_backend                        # noqa: E402
from icraft.zg330backend import ZG330Backend, OcmOpt, SegmentType  # noqa: E402

DEV_URL = 'axi://zg330aiu?npu=0x40000000&dma=0x80000000'
OUT = '/root/glc/seg_manifest.json'
SEGS = ('WEIGHT', 'INSTR', 'FTMP', 'INPUT', 'OUTPUT')
KEEP = []


def short(e):
    m = [l for l in str(e).splitlines() if 'xception info' in l or 'Check failed' in l]
    return m[-1].strip()[:110] if m else str(e)[:110]


key = sys.argv[1]
use_seg = '--use-seg' in sys.argv
base, shapes, vids = D.SUB[key]

old = {}
if os.path.exists(OUT):
    with open(OUT) as f:
        old = json.load(f).get(key, {})

dev = xrt.Device.Open(DEV_URL)
net = xir.Network.CreateFromJsonFile(base + '.json')
net.lazyLoadParamsFromFile(base + '.raw')
nv = net.view(0).setOutputsOrderByValueIds(list(vids))
sess = xrt.Session.Create([ZG330Backend, host_backend.HostBackend], nv,
                          [dev, xrt.HostDevice.Default()])
be = ZG330Backend(sess.backends[0])
be.ocmOptimize(OcmOpt.OPTION1)

locked = []
if use_seg:
    region = dev.getMemRegion('plddr')
    for nm in SEGS:
        sz = int(old.get(nm, 0))
        if sz <= 0:
            continue
        try:
            c = region.malloc(sz, False, 4096)
            KEEP.append(c)
            be.userReuseSegment(c, getattr(SegmentType, nm))
            locked.append(nm)
        except Exception as e:                                    # noqa: BLE001
            print('  [%s] 钉 %s(%.1fMB) ✗ %s' % (key, nm, sz / 1048576.0, short(e)), flush=True)

t0 = time.time()
sess.apply()
print('%s apply %.2f s   已钉: %s' % (key, time.time() - t0, locked or '无'), flush=True)

sizes = {}
for st, ps in be.phy_segment_map.items():
    sizes[str(st).split('.')[-1]] = int(ps.byte_size)

man = {}
if os.path.exists(OUT):
    with open(OUT) as f:
        man = json.load(f)
man[key] = sizes
with open(OUT, 'w') as f:
    json.dump(man, f, indent=1, sort_keys=True)

same = all(int(old.get(k, -1)) == int(sizes.get(k, -1)) for k in SEGS)
print('%s -> %s' % (key, {k: sizes.get(k, 0) for k in SEGS}), flush=True)
print('  与上一轮相同: %s' % same, flush=True)
print('MANIFEST_OK' if same else 'MANIFEST_CHANGED')
