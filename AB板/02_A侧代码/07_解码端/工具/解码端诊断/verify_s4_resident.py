#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""verify_s4_resident.py —— 证明"常驻路径算出来的 s4 输出"与 icraft-run 逐字节一致

为什么必须做：常驻 forward 第 2 次开始返回 0.00 s 且输出完全相同 —— 这是
`glc_rsd.py` 里记录过的已知坑（"forward 直接跳过重算，NPU 一直在算第一张图的数据，
表现上还很'快'，纯属假象"）。所以**快不等于对**，必须拿 icraft-run 的产出做基准比对。

基准：/root/tp5603_drv/decode_run/run_s4/log/s4_gs_generator/ftmpSFB/4107.ftmp
      （由 decode_board.py 那一次 icraft-run 跑出来的，已验证能出 PNG）
"""
import hashlib
import io
import os
import sys
import time

import numpy as np

from icraft import host_backend, xir, xrt
from icraft.zg330backend import OcmOpt, ZG330Backend

DEV_URL = "axi://zg330aiu?npu=0x40000000&dma=0x80000000"
IN_FTMP = "/root/tp5603_drv/decode_run/run_s4/in0.ftmp"
REF = "/root/tp5603_drv/decode_run/run_s4/log/s4_gs_generator/ftmpSFB/4107.ftmp"


def md5(b):
    return hashlib.md5(b).hexdigest()


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "s4_int8"
    base = "/root/glc/models/%s/s4_gs_generator_ZG" % which
    out_ftmp = "/root/s4_resident_out.ftmp"

    print("=== 基准（icraft-run 产出）===")
    if not os.path.exists(REF):
        raise SystemExit("没有基准文件 %s" % REF)
    ref_blob = open(REF, "rb").read()
    print("  %s  %d B  md5=%s" % (os.path.basename(REF), len(ref_blob), md5(ref_blob)))

    print("\n=== 常驻路径 ===")
    dev = xrt.Device.Open(DEV_URL)
    dev.reset(1)
    t = time.time(); net = xir.Network.CreateFromJsonFile(base + ".json"); t1 = time.time() - t
    t = time.time(); net.lazyLoadParamsFromFile(base + ".raw"); t2 = time.time() - t
    nv = net.view(0).setOutputsOrderByValueIds([4107])
    t = time.time()
    sess = xrt.Session.Create([ZG330Backend, host_backend.HostBackend], nv,
                              [dev, xrt.HostDevice.Default()])
    t3 = time.time() - t
    try:
        ZG330Backend(sess.backends[0]).ocmOptimize(OcmOpt.OPTION1)
    except Exception:
        pass
    sess.enableTimeProfile(True)
    t = time.time(); sess.apply(); t4 = time.time() - t
    print("  载入: json %.2f  raw %.2f  sess %.2f  apply %.2f  = %.2f s"
          % (t1, t2, t3, t4, t1 + t2 + t3 + t4))

    vals = list(net.inputs())
    tt = vals[0].tensorType()
    shp = list(tt.shape)
    a = np.fromfile(IN_FTMP, dtype=np.float32)
    n = int(np.prod(shp))
    if a.size != n:
        a = a[:n] if a.size >= n else np.concatenate([a, np.zeros(n - a.size, np.float32)])
    a = np.ascontiguousarray(a.reshape(shp).astype(np.float32))

    tt.setShape(list(a.shape))
    t = time.time()
    out = sess.forward([xrt.Tensor(a, tt)])
    tf = time.time() - t
    bio = io.BytesIO()
    out[0].dump(bio, "SFB")
    blob = bio.getvalue()
    open(out_ftmp, "wb").write(blob)
    print("  首次 forward %.2f s -> %s  %d B  md5=%s" % (tf, out_ftmp, len(blob), md5(blob)))

    print("\n=== 比对 ===")
    print("  长度: 基准 %d  常驻 %d  %s" % (len(ref_blob), len(blob),
                                          "一致" if len(ref_blob) == len(blob) else "**不一致**"))
    if len(ref_blob) == len(blob):
        print("  md5 : %s  %s" % ("相同 ✓✓" if md5(ref_blob) == md5(blob) else "**不同 ✗**",
                                  "" if md5(ref_blob) == md5(blob) else
                                  "(基准 %s / 常驻 %s)" % (md5(ref_blob)[:12], md5(blob)[:12])))
        x = np.frombuffer(ref_blob, dtype=np.float32)
        y = np.frombuffer(blob, dtype=np.float32)
        d = np.abs(x - y)
        print("  max|Δ| = %.3e   mean|Δ| = %.3e   非零差异点 = %d/%d"
              % (d.max(), d.mean(), int((d != 0).sum()), d.size))
        print("  基准 mean=%.6f   常驻 mean=%.6f" % (x.mean(), y.mean()))
    print("\nVERIFY_S4_DONE")


if __name__ == "__main__":
    main()
