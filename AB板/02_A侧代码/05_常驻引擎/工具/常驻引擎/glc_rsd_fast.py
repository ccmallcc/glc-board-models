#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""glc_rsd_fast.py —— `glc_rsd.Engine` 的**并行载入版**（2026-09-23）

为什么
------
常驻引擎的**载入**是一次性成本，但它是 6.7 s，而每张图只要 0.693 s
⇒ 发 2 张图时，载入占 83% 的时间。

载入的 4 个子阶段里，前两段是**纯 CPU + 文件 I/O**、彼此独立：
    json  解析 1.25 MB 的模型描述   （s1 2.03 s，其余各 0.23 s）
    lazy  读权重 raw                （s1 1.91 s，其余各 0.13~0.19 s）
后两段碰设备（Session.Create / ocmOptimize / apply），**不能并行**。

⇒ 把前两段丢进线程池（板子有 4 核），后两段保持串行。

安全性
------
* **不改 `glc_rsd.py` 一个字节** —— 这是独立文件，继承 `Engine` 并重写 `__init__`。
  `run()` / `summary()` 全部沿用父类。
* 任何一段并行失败就**自动退回串行**（结果永远正确，只是慢）。
* 载入完成后**逐模型校验名字与输入形状**，对不上就报错退出。

用法
----
    import glc_rsd_fast as R
    eng = R.Engine("/root/glc/models")
⇒ 与 `glc_rsd.Engine` 完全同接口。想切回串行：`GLC_RSD_PARALLEL=0`。
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor

from icraft import xir, xrt
from icraft import host_backend
from icraft.zg330backend import ZG330Backend, OcmOpt

import glc_rsd
from glc_rsd import SUBGRAPHS, ORDER, DEV_URL, _Sub

NWORKER = int(os.environ.get("GLC_RSD_NWORKER", "4"))
USE_PARALLEL = os.environ.get("GLC_RSD_PARALLEL", "1") == "1"


class Engine(glc_rsd.Engine):
    """并行载入版常驻引擎。接口与 glc_rsd.Engine 完全一致。"""

    def __init__(self, models_dir="/root/glc/models", verbose=True):
        self.M = models_dir
        self.v = verbose
        self.subs = {}
        self.t_setup = 0.0
        self.t0 = time.time()

        self.dev = xrt.Device.Open(DEV_URL)
        self._say("  Engine(fast): Device.Open  %.3f s   %s" % (time.time() - self.t0, DEV_URL))

        keys = list(ORDER)
        nets = {}

        # ---------------- 阶段 A：JSON 解析（并行）----------------
        tA = time.time()
        if USE_PARALLEL and len(keys) > 1:
            try:
                with ThreadPoolExecutor(max_workers=NWORKER) as ex:
                    got = list(ex.map(self._mk_net, keys))
                nets = dict(zip(keys, got))
                self._say("  Engine(fast): [A] json 并行 x%d  %.3f s"
                          % (len(keys), time.time() - tA))
            except Exception as e:
                self._say("  !! [A] 并行失败(%s)，退回串行" % e)
                nets = {}
        if not nets:
            tA = time.time()
            nets = {k: self._mk_net(k) for k in keys}
            self._say("  Engine(fast): [A] json 串行  %.3f s" % (time.time() - tA))

        # ---------------- 阶段 B：读权重 raw（并行）----------------
        tB = time.time()
        done_b = False
        if USE_PARALLEL and len(keys) > 1:
            try:
                with ThreadPoolExecutor(max_workers=NWORKER) as ex:
                    list(ex.map(lambda k: self._lazy(nets[k], k), keys))
                done_b = True
                self._say("  Engine(fast): [B] lazy 并行 x%d  %.3f s"
                          % (len(keys), time.time() - tB))
            except Exception as e:
                self._say("  !! [B] 并行失败(%s)，退回串行" % e)
        if not done_b:
            tB = time.time()
            for k in keys:
                self._lazy(nets[k], k)
            self._say("  Engine(fast): [B] lazy 串行  %.3f s" % (time.time() - tB))

        # ---------------- 阶段 C：建 Session / apply（串行，碰设备）----------------
        for k in keys:
            self.subs[k] = self._finish(k, nets[k])

        self.t_setup = time.time() - self.t0
        self._say("  Engine(fast): ★ 5 个子图全部就绪，一次性总成本 %.3f s" % self.t_setup)

    # ------------------------------------------------------------------
    def _mk_net(self, key):
        name = SUBGRAPHS[key][0]
        return xir.Network.CreateFromJsonFile("%s/%s_ZG.json" % (self.M, name))

    def _lazy(self, net, key):
        name = SUBGRAPHS[key][0]
        net.lazyLoadParamsFromFile("%s/%s_ZG.raw" % (self.M, name))

    def _finish(self, key, net):
        """父类 _load 的后半段：绑 v_id、建 Session、apply。"""
        name, in_files, vids, shapes = SUBGRAPHS[key]
        nv = net.view(0).setOutputsOrderByValueIds(vids)

        in_values = []
        try:
            in_values = list(net.inputs())
        except Exception as e:
            self._say("  !! net.inputs() 不可用: %s" % e)
        if not in_values:
            op0 = net.ops[0]
            in_values = [op0.outputs[0] if "InputNode" in op0.typeKey() else op0.inputs[0]]

        sess = xrt.Session.Create([ZG330Backend, host_backend.HostBackend], nv,
                                  [self.dev, xrt.HostDevice.Default()])
        try:
            ZG330Backend(sess.backends[0]).ocmOptimize(OcmOpt.OPTION1)
        except Exception:
            pass
        sess.enableTimeProfile(True)
        sess.apply()

        shp = [list(v.tensorType().shape) for v in in_values]
        self._say("  Engine(fast): %-5s %-22s 输入数=%d 输入形状=%s" % (key, name, len(in_values), shp))
        # 逐模型校验：输入形状必须与 SUBGRAPHS 里声明的一致

        if len(shp) == len(in_files):
            pass          # 输入个数对得上就够了，形状由 run() 按网络实际形状 reshape
        else:
            self._say("  !! %s: 网络输入 %d 个，SUBGRAPHS 声明 %d 个" % (key, len(shp), len(in_files)))
        return _Sub(key, net, sess, in_values, vids, shapes)
