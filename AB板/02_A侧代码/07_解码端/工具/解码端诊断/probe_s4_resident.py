#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""probe_s4_resident.py —— s4 走「常驻引擎」到底能省多少（2026-10-15）

背景（全部实测）：
    decode_board.py 用 `subprocess.run(icraft-run)` 跑 s4：**47.3 s**（干净复测 **29.6 s**）
    而 `icraft-run --log_time` 自己报告：
        Load Json Time: 2892.9 ms
        Load Raw  Time: 3827.2 ms
        全部 1116 个算子 wall 合计: **1304.3 ms**（total_hard_time 601.5 ms）
      ⇒ 载入 + 算子 = 8 s，**剩下 20~39 s 不在任何一项里**
    而且 1114 个算子**全部标 (H)** —— 全跑在 Host(CPU) 上，ZG330 一个都没接。

本脚本照抄 `glc_rsd.Engine` 的做法（那是编码端已经验证过的常驻路径：
s1 载入一次 ~4.9 s，之后每次 forward 0.350 s，与 icraft-run 逐字节一致），
把 s4 **常驻载入一次**、反复 forward，看能不能把那段"每进程一次"的外围开销绕掉。

用法：
    python3 probe_s4_resident.py [s4_int8|s4_bf16] [forward次数]
"""
import io
import json
import os
import sys
import time

import numpy as np

from icraft import host_backend, xir, xrt
from icraft.zg330backend import OcmOpt, ZG330Backend

DEV_URL = "axi://zg330aiu?npu=0x40000000&dma=0x80000000"
MODELS = "/root/glc/models"
IN_FTMP = os.environ.get("GLC_S4_IN", "/root/tp5603_drv/decode_run/run_s4/in0.ftmp")


def output_vids(base):
    d = json.load(open(base + ".json", encoding="utf-8"))
    ops = d.get("ops", [])
    hits = []
    for o in ops:
        tk = str(o.get("_type_key", ""))
        if tk.endswith("::Output") or tk.endswith("Output"):
            hits = [v for v in (o.get("inputs") or []) if isinstance(v, int)]
    if hits:
        return hits
    # 诊断：s4 的 json 结构可能和 s1/s2/s3 不一样
    print("  !! 没找到 Output 节点。最后 4 个 op 的 _type_key：")
    for o in ops[-4:]:
        print("       %-40s inputs=%s" % (str(o.get("_type_key"))[:40], o.get("inputs")))
    from collections import Counter
    c = Counter(str(o.get("_type_key", "")).split("::")[-1] for o in ops)
    print("     op 类型计数(尾部10): %s" % c.most_common()[-10:])
    return []


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "s4_int8"
    nfw = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    base = os.path.join(MODELS, which, "s4_gs_generator_ZG")
    print("模型 %s   (raw %.1f MB)" % (base, os.path.getsize(base + ".raw") / 1048576.0))

    T0 = time.time()
    dev = xrt.Device.Open(DEV_URL)
    print("  Device.Open            %6.2f s" % (time.time() - T0))
    try:
        dev.reset(1)          # ★ 必须在 Open 之后立刻 reset，否则残留状态污染内存规划
        print("  dev.reset(1)           ok")
    except Exception as e:
        print("  dev.reset(1) 失败: %s" % e)

    t = time.time(); net = xir.Network.CreateFromJsonFile(base + ".json"); t_json = time.time() - t
    t = time.time(); net.lazyLoadParamsFromFile(base + ".raw"); t_raw = time.time() - t
    vids = output_vids(base)
    if not vids:
        # decode_board.py 的注释里记着 s4 的正确输出 v_id 是 4107（4115 在该模型里不存在）
        cand = 4107 if which == "s4_int8" else 4107
        print("  !! 回退到已知 v_id = %d（decode_board.py 实测记录）" % cand)
        vids = [cand]
    print("  Load Json              %6.2f s" % t_json)
    print("  Load Raw               %6.2f s   (输出 v_id=%s)" % (t_raw, vids))

    t = time.time(); nv = net.view(0).setOutputsOrderByValueIds(vids); t_view = time.time() - t
    t = time.time()
    sess = xrt.Session.Create([ZG330Backend, host_backend.HostBackend], nv,
                              [dev, xrt.HostDevice.Default()])
    t_sess = time.time() - t
    try:
        ZG330Backend(sess.backends[0]).ocmOptimize(OcmOpt.OPTION1)
    except Exception as e:
        print("  ocmOptimize 跳过: %s" % e)
    sess.enableTimeProfile(True)
    t = time.time(); sess.apply(); t_apply = time.time() - t
    print("  view %.2f  Session.Create %.2f  apply %.2f" % (t_view, t_sess, t_apply))
    t_load = t_json + t_raw + t_view + t_sess + t_apply
    print("  ★ 常驻载入合计          %6.2f s（对照 icraft-run: json 2.89 + raw 3.83 = 6.72 s）"
          % t_load)

    # ---- 输入：直接用 decode_board.py 写好的那份 ----
    vals = list(net.inputs())
    tt = vals[0].tensorType()
    shp = list(tt.shape)
    a = np.fromfile(IN_FTMP, dtype=np.float32)
    n = int(np.prod(shp))
    if a.size != n:
        print("  输入文件 %d float，网络要 %s(%d) -> 截断/补零" % (a.size, shp, n))
        a = a[:n] if a.size >= n else np.concatenate([a, np.zeros(n - a.size, np.float32)])
    a = np.ascontiguousarray(a.reshape(shp).astype(np.float32))
    print("  输入 %s  %d B" % (shp, a.nbytes))

    ts = []
    for k in range(nfw):
        tt.setShape(list(a.shape))
        ten = xrt.Tensor(a, tt)          # ★ 每次新建，不复用（复用会导致 forward 被跳过）
        t = time.time()
        out = sess.forward([ten])
        tf = time.time() - t
        ts.append(tf)
        bio = io.BytesIO()
        out[0].dump(bio, "SFB")
        arr = np.frombuffer(bio.getvalue(), dtype=np.float32)
        print("  forward #%d            %6.2f s   输出 %d float  mean=%.5f" % (k + 1, tf, arr.size, arr.mean()))

    print()
    print("  ★ 结论：常驻后首次 forward %.2f s，稳态 %.2f s" % (ts[0], min(ts)))
    print("     对照 icraft-run 每进程一次：实测 29.6 ~ 47.3 s")
    print("     常驻省掉的 = 每进程一次的 (进程启动 + Device.Open + 载入 + 外围)")
    print("S4_RESIDENT_DONE")


if __name__ == "__main__":
    main()
