#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""resident_read_pattern.py —— 常驻推理引擎的**最小读数范式**（可直接照搬）

=============================================================================
 ★★★ 三条关键线，缺一条就会**静默出错**（结果看着正常，其实是旧的）
=============================================================================

    ①  tt.setShape(...); ten = xrt.Tensor(a, tt)   每次都**新建** Tensor
           —— 复用 tensor + write() 覆盖数据，框架会认为"输入没变"而**跳过重算**

    ②  out = sess.forward([ten])                   **同步调用，没有单独的等待**
           —— 不需要 waitForReady() / isReady()；我们从来没用过它们

    ③  dev.reset(1)                                **每帧 forward 之后必须 reset** ★
           —— 就是这一行。少了它，NPU 不重读输入、一直算旧数据，
              表现是"永远返回第一次的结果"，而且**耗时从 0.35 s 塌到 0.004 s**

实测（A 侧 s1 常驻 Session，输入序列 A A B C A B，三个真实不同输入）：

    每帧 reset   →  输出 A A B C A B 一一对应，耗时稳定 0.349 s   ✅
    去掉 reset   →  六个输出**全是 A 的结果**，耗时 0.004 s       ✗

⚠️ reset 要传下去：进程里 `fork`/`exec` 出的子进程是另一个设备句柄。
   我们生产路径用环境变量 `GLC_RSD_RESET=each` 传这个开关。

用法：
    python3 resident_read_pattern.py --model <模型基名> [--vids 3310,3314] [--seq AABCAB]
    例如 python3 resident_read_pattern.py --model /root/glc/models/s1_encoder_ga_hyper_ZG \
                                          --vids 3310,3314
=============================================================================
"""
import argparse
import hashlib
import io
import os
import time

import numpy as np

from icraft import host_backend, xir, xrt
from icraft.zg330backend import OcmOpt, ZG330Backend

DEV_URL = "axi://zg330aiu?npu=0x40000000&dma=0x80000000"


def md5(b):
    return hashlib.md5(b).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="模型基名（不含 .json/.raw）")
    ap.add_argument("--vids", required=True, help="输出 v_id，逗号分隔，如 3310,3314")
    ap.add_argument("--seq", default="AABCAB", help="要喂的输入序列（字母对应 --in-* 文件）")
    ap.add_argument("--in-a", default="/root/glc/inputs_photo/p1.ftmp")
    ap.add_argument("--in-b", default="/root/glc/inputs_photo/p2.ftmp")
    ap.add_argument("--in-c", default="/root/glc/inputs_photo/p3.ftmp")
    ap.add_argument("--noreset", action="store_true",
                    help="对照组：故意不 reset（应当报 ✗ —— 用来证明判据有判别力）")
    a = ap.parse_args()

    vids = [int(x) for x in a.vids.split(",")]
    base = a.model
    if base.endswith((".json", ".raw")):
        base = base.rsplit(".", 1)[0]

    # ---------------- 一次性：打开设备、载入、建会话 ----------------
    dev = xrt.Device.Open(DEV_URL)
    dev.reset(1)                                     # Open 之后先 reset 一次
    net = xir.Network.CreateFromJsonFile(base + ".json")
    net.lazyLoadParamsFromFile(base + ".raw")
    nv = net.view(0).setOutputsOrderByValueIds(vids)
    sess = xrt.Session.Create([ZG330Backend, host_backend.HostBackend], nv,
                              [dev, xrt.HostDevice.Default()])
    try:
        ZG330Backend(sess.backends[0]).ocmOptimize(OcmOpt.OPTION1)
    except Exception:
        pass
    sess.enableTimeProfile(True)
    sess.apply()

    vals = list(net.inputs())                        # ★ 用官方接口拿输入，别自己猜
    tt = vals[0].tensorType()
    shp = list(tt.shape)
    n = int(np.prod(shp))

    data = {}
    for k, p in (("A", a.in_a), ("B", a.in_b), ("C", a.in_c)):
        v = np.fromfile(p, dtype=np.float32)
        if v.size != n:
            v = v[:n] if v.size >= n else np.concatenate([v, np.zeros(n - v.size, np.float32)])
        data[k] = np.ascontiguousarray(v.reshape(shp).astype(np.float32))

    def run_one(key):
        """★ 这就是全部读数逻辑 —— 三条关键线都在这里"""
        tt.setShape(list(data[key].shape))
        ten = xrt.Tensor(data[key], tt)              # ① 每帧新建
        t0 = time.time()
        out = sess.forward([ten])                    # ② 同步，无 wait
        el = time.time() - t0
        if not a.noreset:
            dev.reset(1)                             # ③ 每帧 reset ★
        bio = io.BytesIO()
        out[0].dump(bio, "SFB")                      # 取输出（与 icraft-run 同款格式）
        return md5(bio.getvalue()), el, bio.getvalue()

    # ---------------- 跑序列 ----------------
    seq = [c for c in a.seq if c in "ABC"]
    print("模型 %s   vids %s   输入 %s   每帧 reset = %s"
          % (os.path.basename(base), vids, shp, not a.noreset))
    res = []
    for i, k in enumerate(seq):
        h, el, _ = run_one(k)
        res.append((k, h, el))
        print("  #%-3d %s -> %s  %.3f s" % (i + 1, k, h[:16], el))

    # ---------------- 判定：判据必须**与参照无关** ----------------
    #   ⚠️ 别用"输出 == 事先算好的参照值"——参照值是同一条（可能错的）路径算出来的，
    #      会被同一个 bug 一起污染，于是永远报 OK。我们踩过这个坑。
    by_in = {}
    for k, h, el in res:
        by_in.setdefault(k, set()).add(h)
    reps = {k: sorted(v)[0] for k, v in by_in.items()}
    stable = all(len(v) == 1 for v in by_in.values())
    distinct = len(set(reps.values())) == len(reps)
    fast = [el for _, _, el in res if el < 0.05]

    print()
    print("  ① 同输入重复出现 ⇒ 结果稳定     : %s" % ("✅" if stable else "✗"))
    print("  ② 不同输入       ⇒ 结果互不相同 : %s  %s"
          % ("✅" if distinct else "✗", " ".join("%s=%s" % (k, reps[k][:12]) for k in sorted(reps))))
    print("  ③ 耗时无异常小值                : %s  最小 %.3f s"
          % ("✅" if not fast else "✗", min(el for _, _, el in res)))

    ok = stable and distinct and not fast
    print()
    print("  %s" % ("✅ 读数可靠" if ok else
                   "✗ 读数不可靠 —— 生产链路上会有静默错误（结果看着正常，其实是旧的）"))
    print("RESIDENT_READ_PATTERN_DONE")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
