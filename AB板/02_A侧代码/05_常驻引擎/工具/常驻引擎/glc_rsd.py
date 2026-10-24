#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""glc_rsd.py —— GLC 常驻 NPU 引擎（2026-10-08）

为什么需要它
------------
`glc_board_full.py` 用 `subprocess.run(icraft-run ...)` 跑 5 个子图，**每跑一张图就重启 5 次进程**。
实测（2026-10-08）：
    icraft-run 跑 S1：wall **6.66 s**，其中 NPU 硬时间只有 **346 ms** ⇒ 95% 是"载入/编译模型"
    而且**与模型体积成正比**（S1 157MB→6.3s、S2 15MB→0.55s、S3 9.4MB→0.49s）
    读 SD 卡只要 0.113 s（1.4 GB/s）⇒ **不是 I/O，是 CPU 侧反序列化**
所以：**把模型载入一次、反复 forward** 才是正解。

本模块做什么
------------
用官方 Python API（`demo_package/deps/modelzoo_utils/pyrtutils/icraft_utils.py` 是同一套写法）
把 5 个子图**一次性**载入，建 5 个常驻 Session，之后每次编码只调 `session.forward()`。

实测（同一台板子，2026-10-08）：
    S1 一次性 ≈ 4.93 s（json 1.92 + lazyLoad 1.91 + apply 0.83 + 其它 0.27）
    S1 forward 每次 = **0.350 s**（≈ 它的 NPU 硬时间 346 ms，开销归零）
    输出与 icraft-run **逐字节一致**（v_id 3310 65536 点、3314 4096 点，max|d| = 0）

接口
----
`Engine.run(key, cwd)` 的**签名与返回值刻意与 glc_board_full.run_npu 完全一致**：
    · 从 cwd/in0.ftmp（必要时 in1.ftmp...）读输入
    · 把输出写到 cwd/logs/<name>/ftmpSFB/<v_id>.ftmp（**与 icraft-run 同路径同格式**，
      这样下游 np.fromfile 的代码一行都不用改）
    · 返回 (outs_nchw, hard_ms, wall_s)
⇒ 只要把 glc_board_full.py 里的 run_npu 换成 Engine.run，其余胶水层原样不动。

⚠️ 两个实测得来的注意点
  1. **输出 tensor 在设备内存（memRegion = AXIZG330AIPLDDRMemRegion, PtrType=ADDR），
     不能直接 np.array()** —— 会抛 `The Tensor's memchunk is of ADDR type, can't be converted to buffer!`。
     必须用 `Tensor.dump(流, "SFB")` 或 `Tensor.read(缓冲, off, n)` 取回。本模块用 dump（与官方 dumpOutputFtmp 一致）。
  2. 每次 forward 之后官方示例会调 `device.reset(1)`；本模块也做，并把它计入每帧耗时。
"""
import io
import os
import time

import numpy as np

from icraft import xir, xrt
from icraft import host_backend
from icraft.zg330backend import ZG330Backend, OcmOpt

# 子图定义 —— 与 glc_board_full.py 的 SUBGRAPHS 逐字一致（不重写、不猜）
SUBGRAPHS = {
    "s1":   ("s1_encoder_ga_hyper", ["in0.ftmp"], [3310, 3314],
             [(1, 16, 16, 256), (1, 4, 4, 256)]),
    "s2":   ("s2_hyperdec_fusion",  ["in0.ftmp"], [184], [(1, 16, 16, 768)]),
    "s3p1": ("s3_phase1", ["in0.ftmp", "in1.ftmp"], [178, 182],
             [(1, 16, 16, 256), (1, 16, 16, 256)]),
    "s3p2": ("s3_phase2", ["in0.ftmp", "in1.ftmp"], [178, 182],
             [(1, 16, 16, 256), (1, 16, 16, 256)]),
    "s3p3": ("s3_phase3", ["in0.ftmp", "in1.ftmp"], [178, 182],
             [(1, 16, 16, 256), (1, 16, 16, 256)]),
}
ORDER = ["s1", "s2", "s3p1", "s3p2", "s3p3"]
DEV_URL = os.environ.get("GLC_DEV_URL", "axi://zg330aiu?npu=0x40000000&dma=0x80000000")
# 每帧 forward 之后要不要 device.reset(1)？
#   官方 pyrt_main_example.py 是"每次 forward 后 reset"，
#   但实测（2026-10-08 批处理）：reset 会把**其它 Session 的内存分配一起作废**
#   ⇒ 第二张图开始 session.forward() 报
#       Exception info : Write failed  (AXIZZ330AIPLDDRMemRegionNode::write -> dmaWrite)
#   实测三种模式的结论见 run() 里 "设备 reset" 那段：最终默认 **perimage**（每张图在 s1 前 reset 一次）。
RESET_MODE = os.environ.get("GLC_RSD_RESET", "perimage")


def to_nchw(a):
    return np.ascontiguousarray(a.transpose(0, 3, 1, 2))


class _Sub(object):
    def __init__(self, key, net, sess, in_values, vids, shapes):
        self.key = key
        self.net = net
        self.sess = sess
        self.in_values = in_values      # list of xir.Value
        self.vids = vids
        self.shapes = shapes
        self.ntry = 0
        self.ntensor = 0       # 建过多少个输入 tensor（只用于头两个打印一次）
        self.t_forward = 0.0
        self.t_reset = 0.0
        self.tin = []          # 只保留**本轮**新建的输入 tensor（见 run() 里的说明；别再累积）


class Engine(object):
    """常驻 NPU 引擎：载入一次，反复 forward。"""

    def __init__(self, models_dir="/root/glc/models", verbose=True):
        self.M = models_dir
        self.v = verbose
        self.subs = {}
        self.t_setup = 0.0
        self.t0 = time.time()
        self.dev = xrt.Device.Open(DEV_URL)
        self._say("  Engine: Device.Open  %.3f s   %s" % (time.time() - self.t0, DEV_URL))
        for key in ORDER:
            self.subs[key] = self._load(key)
        self.t_setup = time.time() - self.t0
        self._say("  Engine: ★ 5 个子图全部就绪，一次性总成本 %.3f s" % self.t_setup)

    def _say(self, s):
        if self.v:
            print(s)
            try:
                import sys
                sys.stdout.flush()
            except Exception:
                pass

    def _load(self, key):
        name, in_files, vids, shapes = SUBGRAPHS[key]
        t = time.time()
        net = xir.Network.CreateFromJsonFile("%s/%s_ZG.json" % (self.M, name))
        t1 = time.time() - t
        t = time.time()
        net.lazyLoadParamsFromFile("%s/%s_ZG.raw" % (self.M, name))
        t2 = time.time() - t
        nv = net.view(0).setOutputsOrderByValueIds(vids)

        # ★ 正确的输入发现方式：net.inputs() / net.outputs()
        #   （踩坑记录：s3 相位是**一个 InputNode 带 2 个 output**，
        #     原来写 `op.outputs[0]` 只能拿到第 1 个 ⇒ 报 "in1.ftmp 找不到对应的网络输入 Value"。
        #     实测：s1 inputs=1/outputs=2；s2 1/1；s3p1~p3 **inputs=2**/outputs=2。）
        in_values = []
        out_values = []
        try:
            in_values = list(net.inputs())
            out_values = list(net.outputs())
        except Exception as e:
            self._say("  !! net.inputs()/outputs() 不可用: %s" % e)
        if not in_values:                      # 兜底：照官方 numpy2Tensor 的写法
            op0 = net.ops[0]
            in_values = [op0.outputs[0] if "InputNode" in op0.typeKey() else op0.inputs[0]]

        t = time.time()
        sess = xrt.Session.Create([ZG330Backend, host_backend.HostBackend], nv,
                                  [self.dev, xrt.HostDevice.Default()])
        try:
            ZG330Backend(sess.backends[0]).ocmOptimize(OcmOpt.OPTION1)
        except Exception:
            pass
        sess.enableTimeProfile(True)
        t3 = time.time() - t
        t = time.time()
        sess.apply()
        t4 = time.time() - t
        self._say("  Engine: %-5s %-22s json %5.2fs  lazy %5.2fs  sess %5.2fs  apply %5.2fs"
                  "  输入数=%d 输入形状=%s"
                  % (key, name, t1, t2, t3, t4, len(in_values),
                     [list(v.tensorType().shape) for v in in_values]))
        return _Sub(key, net, sess, in_values, vids, shapes)

    # ------------------------------------------------------------------
    def run(self, key, cwd):
        """与 glc_board_full.run_npu(key, cwd) 同签名同返回值。"""
        name, in_files, vids, shapes = SUBGRAPHS[key]
        sub = self.subs[key]
        t_wall0 = time.time()

        # ---- 组输入 tensor：**严格按顺序**对应 net.inputs() ----
        #   为什么不能按"大小匹配"：s3 相位的两个输入形状**完全相同**（都是 1,16,16,256），
        #   按大小匹配必然歧义。icraft-run 的 `--input "in0.ftmp;in1.ftmp"` 也是按顺序对应。
        vals = list(sub.in_values)
        if len(vals) != len(in_files):
            print("   !! %s: 网络输入 %d 个，但 SUBGRAPHS 里写了 %d 个输入文件"
                  % (key, len(vals), len(in_files)))
        tens = []
        for j, f in enumerate(in_files):
            fp = os.path.join(cwd, f)
            if not os.path.exists(fp):
                raise RuntimeError("%s: 输入文件不存在 %s" % (key, fp))
            a = np.fromfile(fp, dtype=np.float32)
            if j >= len(vals):
                raise RuntimeError("%s: 输入 %s 找不到对应的网络输入 Value（网络只有 %d 个输入）"
                                   % (key, f, len(vals)))
            tt = vals[j].tensorType()
            shp = list(tt.shape)
            n = int(np.prod(shp))
            if n != a.size:
                print("   !! %s 输入 %s: 文件 %d 个 float32, 网络要 %s(%d) —— 按网络形状截断/补零"
                      % (key, f, a.size, shp, n))
                if a.size < n:
                    a = np.concatenate([a, np.zeros(n - a.size, dtype=np.float32)])
                else:
                    a = a[:n]
            a = np.ascontiguousarray(a.reshape(shp).astype(np.float32))

            # ★ 复用输入 tensor（重要）
            #   原来每次 run 都 `xrt.Tensor(a, tt)` 新建一个 ⇒ **设备内存只分配不释放**，
            #   常驻进程里跑到第二张图就报
            #       Exception info : Write failed (AXIZG330AIPLDDRMemRegionNode::write -> dmaWrite)
            #   （icraft-run 每张图退一次进程、全部释放，所以它不会暴露这个问题。）
            #   现在：第一次为每个输入建一个常驻 Tensor，之后只用 write() 覆盖数据。
            # ⚠️ 实测教训（2026-10-08）：**不要复用 tensor + write()**！
            #   曾经为了"省设备内存"改成"建一次常驻 tensor、之后 write() 覆盖"，
            #   结果：容器全错（7 张里 5 张产出**完全相同**的 23544 B），
            #   因为 write() 之后框架并不认为输入变了 ⇒ forward 直接**跳过重算**，
            #   NPU 一直在算第一张图的数据；表现上还很"快"（0.02~0.05 s，纯属假象）。
            #   正确做法：**每次调用都新建 Tensor**（与官方 numpy2Tensor 一致）。
            #   设备内存的回收由"每张图走一遍 GLG 的 PL 段 + 不重复 Open 设备"来兜住。
            tt.setShape(list(a.shape))
            t_new = xrt.Tensor(a, tt)
            sub.ntensor += 1
            if sub.ntensor <= 2:               # 只在头两个上打一次，别刷屏
                self._say("     [%s] 新建输入 tensor #%d  shape=%s  %d B"
                          % (key, sub.ntensor, list(a.shape), a.nbytes))
            tens.append(t_new)

        # ★★ 2026-10-17 修：这里原来是 `sub.tin.append(t_new)`（注释写"只留引用便于排查"），
        #   **只增不减、永不释放** ⇒ 常驻 daemon 每帧攒 8 个输入 tensor。
        #   实测代价：单跑 s1 30 次 RSS +0.78 MB/次 ⇒ 一整帧 **3.9 MB/帧**
        #   ⇒ 993 MB 的板子连续发 ~137 帧（约 2 分钟）就把内存吃光。
        #   现在只保留**本轮**的这几个：上一轮的在赋值时引用计数归零、立刻回收。
        #   （tensor 只在本次 forward 期间需要活着，forward 是同步的，见下面 sess.forward。）
        sub.tin = tens

        # ---- 设备 reset：★ 每张图一次（在第一个子图 s1 之前）----
        #   三个模式的实测结论（2026-10-08）：
        #     none     : 不 reset  -> 不崩，但 **输入数据不更新**，NPU 一直算旧数据
        #                              （单张容器 336B -> 9868B，批量 7 张里 5 张产出完全相同）
        #     each     : 每次 forward 后 reset -> **单张正确**（336B，与 icraft-run 逐字节一致），
        #                              但批量到第二张图崩：`Write failed`
        #     perimage : 每张图在 s1 之前 reset 一次 <- 本默认值，兼顾两者
        if RESET_MODE == "perimage" and key == ORDER[0]:
            try:
                self.dev.reset(1)
            except Exception as e:
                print("   !! 每张图 reset 失败: %s" % e)

        # ---- forward ----
        tf0 = time.time()
        out = sub.sess.forward(tens)
        tf = time.time() - tf0
        sub.t_forward += tf

        # ---- 把输出写成与 icraft-run 同路径同格式的 ftmp ----
        outdir = os.path.join(cwd, "logs", name, "ftmpSFB")
        if not os.path.isdir(outdir):
            os.makedirs(outdir)
        outs = []
        for i, v in enumerate(vids):
            o = out[i]
            bio = io.BytesIO()
            o.dump(bio, "SFB")
            blob = bio.getvalue()
            with open(os.path.join(outdir, "%d.ftmp" % v), "wb") as fh:
                fh.write(blob)
            a = np.frombuffer(blob, dtype=np.float32).reshape(shapes[i])
            outs.append(to_nchw(a))

        # ---- 设备 reset：**默认不做**（见文件顶部 RESET_MODE 的说明）----
        #   实测：每个 forward 后 reset(1) 会把其它 Session 的内存分配一起作废，
        #   第二张图起报 `Write failed`（AXIZG330AIPLDDRMemRegionNode::write -> dmaWrite）。
        tr0 = time.time()
        if RESET_MODE == "each":
            try:
                self.dev.reset(1)
            except Exception as e:
                print("   !! dev.reset 失败: %s" % e)
        sub.t_reset += time.time() - tr0
        sub.ntry += 1

        wall = time.time() - t_wall0
        return outs, float("nan"), wall

    def summary(self):
        lines = ["  Engine 汇总：一次性 %.3f s，共 %d 次 forward"
                 % (self.t_setup, sum(s.ntry for s in self.subs.values()))]
        for k in ORDER:
            s = self.subs[k]
            if s.ntry:
                lines.append("    %-5s  %2d 次  forward 合计 %.3f s  平均 %.4f s  reset 合计 %.3f s"
                             % (k, s.ntry, s.t_forward, s.t_forward / s.ntry, s.t_reset))
        return "\n".join(lines)
