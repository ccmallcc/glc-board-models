# -*- coding: utf-8 -*-
"""从 GLC checkpoint 导出板端胶水层需要的**全部**常量（只有两张表）。

推导依据（逐行核对过源码，不是猜）：
    board_e2e.py:271  z_idx = model.z_vq.get_indices(z)
    vqgan_arch.py:97  get_indices   -> 需要 self.embedding.weight (16384 x 256)
    common_model.py:74 y_spatial_prior_reduction = nn.Conv2d(N*3, N*1, 1)
                      -> 需要 weight (256, 768, 1, 1) + bias (256,)
    common_model.py:56 separate_prior -> params.chunk(3,1) + clamp_min(0.5) + 倒数
                      -> **无权重**，纯运算
    common_model.py:15 quant -> round  -> 无权重
    common_model.py:163 get_mask_four_parts -> 纯索引  -> 无权重

其余（S1/S2/S3p1..3）全部在 NPU 上跑，不需要权重。
"""
import os
import sys

import numpy as np
import torch

REPO = "/mnt/e/fudanwei/工作区/GLC-main/GLC-main"
CKPT = REPO + "/pretrained/GLC_image.pth.tar"
OUT = "/mnt/e/fudanwei/工作区/_board_run/glue_consts"

sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "src", "utils"))

import types
stub = types.ModuleType("src.utils.metric_image")
stub.evaluate_quality = lambda *x, **k: None
sys.modules["src.utils.metric_image"] = stub

from src.models.image_model import GLC_Image
from src.utils.test_utils import get_state_dict, init_func

init_func()
model = GLC_Image(inplace=True)
model.load_state_dict(get_state_dict(CKPT), strict=True)
model.eval()

os.makedirs(OUT, exist_ok=True)


def dump(name, t):
    a = t.detach().cpu().numpy()
    np.save(os.path.join(OUT, name + ".npy"), a)
    print("  %-34s %-18s %s" % (name, str(a.shape), a.dtype))


print("=== 导出胶水层常量 ===")
dump("z_codebook", model.z_vq.embedding.weight)          # (16384, 256)
dump("ysp_reduce_w", model.y_spatial_prior_reduction.weight)  # (256, 768, 1, 1)
dump("ysp_reduce_b", model.y_spatial_prior_reduction.bias)    # (256,)
dump("q_enc_param", model.q_enc)                          # (64,256,1,1)  S4 解码用
dump("q_dec_param", model.q_dec)                          # (64,256,1,1)
print("z_vq: codebook_size=%d emb_dim=%d" % (model.z_vq.codebook_size, model.z_vq.emb_dim))
print("N=%d" % model.N)
print("-> %s" % OUT)
