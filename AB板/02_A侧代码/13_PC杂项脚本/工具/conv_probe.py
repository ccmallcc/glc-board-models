#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""关键实验：1x1 卷积的 numpy-vs-torch 末位差，会不会传导到 S3 的输出？

这是一个**可以判定**的实验，不需要猜：
    两个 common 我都手里有 ——
      common_np    = 本脚本(numpy fp32)算的
      common_torch = run/ 那条链路(torch)算的，就在 ref_stage/run/s3p1/in1.ftmp
    把它们分别喂给**同一个** S3p1 子图（同一个 y_hat_so_far），比对输出。
    若输出逐位相同 -> INT8 量化把那点末位差吸收掉了 -> 板端链路与 PC 链路等价。
"""
import os
import shutil
import sys

import numpy as np

import glc_board_full as G

REF = G.REF
RUN = G.RUN
PACK = G.PACK
C, H, W = 256, 16, 16


def main():
    print("############ 1x1 卷积影响判定 ############")
    codebook = np.load(G.CONSTS + "/z_codebook.npy")
    ysp_w = np.load(G.CONSTS + "/ysp_reduce_w.npy").reshape(256, 768)
    ysp_b = np.load(G.CONSTS + "/ysp_reduce_b.npy")

    print("\n[1] S1 (NPU)")
    (y, z), _, _ = G.run_npu("s1", "%s/s1" % RUN)

    print("[2] z_vq + S2 (NPU)")
    zz = np.ascontiguousarray(z.transpose(0, 2, 3, 1)).reshape(-1, 256)
    d = (zz ** 2).sum(1, keepdims=True) + (codebook ** 2).sum(1)[None, :] - 2.0 * (zz @ codebook.T)
    z_idx = np.argmin(d, axis=1).astype(np.int32)
    codebook[z_idx].reshape(1, 4, 4, 256).astype(np.float32).tofile("%s/s2/in0.ftmp" % RUN)
    (params,), _, _ = G.run_npu("s2", "%s/s2" % RUN)
    np.save(PACK + "/full_img0/params.npy", params)

    print("[3] 胶水 + phase 0")
    quant_step, scales0, means0 = np.split(params, 3, axis=1)
    qs = np.maximum(quant_step, np.float32(0.5))
    q_enc = (np.float32(1.0) / qs).astype(np.float32)
    common_np = (ysp_w @ params.reshape(768, -1) + ysp_b[:, None]).astype(np.float32)
    common_np = common_np.reshape(1, C, H, W)
    np.save(PACK + "/full_img0/common_np.npy", common_np)

    common_torch = np.fromfile(REF + "/run/s3p1/in1.ftmp",
                               dtype=np.float32).reshape(1, H, W, C)
    common_torch_nchw = G.to_nchw(common_torch)
    np.save(PACK + "/full_img0/common_torch.npy", common_torch_nchw)

    dd = np.abs(common_np.astype(np.float64) - common_torch_nchw.astype(np.float64))
    print("    common_np vs common_torch : 不同 %d/%d  最大绝对差 %.3e"
          % (int((common_np != common_torch_nchw).sum()), common_np.size, dd.max()))

    masks = G.make_masks(C, H, W)
    mask_bool = [m.astype(bool) for m in masks]
    y_scaled = (y * q_enc).astype(np.float32)
    means_hat = (means0 * masks[0]).astype(np.float32)
    y_q = np.round(((y_scaled - means_hat) * masks[0]).astype(np.float32)).astype(np.float32)
    y_hat_so_far = (y_q + means_hat).astype(np.float32)
    yh_nhwc = G.nhwc(y_hat_so_far)

    print("\n[4] 用两个 common 各跑一次 S3p1（同一个 y_hat_so_far）")
    res = {}
    for tag, cm in (("np", common_np), ("torch", common_torch_nchw)):
        wd = "/root/glc/probe_%s" % tag
        if os.path.isdir(wd):
            shutil.rmtree(wd)
        os.makedirs(wd)
        yh_nhwc.tofile(wd + "/in0.ftmp")
        G.nhwc(cm).tofile(wd + "/in1.ftmp")
        (s_, m_), _, _ = G.run_npu("s3p1", wd)
        res[tag] = (s_, m_)

    print("\n[5] 判定")
    for i, nm in enumerate(("scales", "means")):
        a = res["np"][i]
        b = res["torch"][i]
        nd = int((a != b).sum())
        mx = float(np.abs(a.astype(np.float64) - b.astype(np.float64)).max())
        print("    S3p1 输出 %-6s : 不同 %d/%d  最大绝对差 %.3e  -> %s"
              % (nm, nd, a.size, mx, "**逐位相同**" if nd == 0 else "有差异"))
    ok = all(np.array_equal(res["np"][i], res["torch"][i]) for i in range(2))
    print("\n    ==> %s" % ("**1x1 卷积的末位差被 INT8 NPU 完全吸收**"
                            if ok else "**差异传导到了 S3 输出**"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
