# ==============================================================================
# 版本横幅（2026-10-18 加）：本文件被**就地改过**，板上可能还是旧版。
#   当前标签   : v20261018-512param
#   上一版(板上): md5 907bbe93 …  ← 回滚用它，历史副本见
#               工具/_历史_板端文件/glc_board_full.907bbe93.py
#   上一版来源 : git 824eed0:工具/板端程序/glc_board_full.py
#   这一版改了什么 / 回滚步骤：见 `工具/版本对照_板端文件.md`、`工具/回归/结果_预热引擎_20261017.md` 附二十五
#   ⚠️ 本文件**不写自己的 md5**（自指会变）。现版 md5 只在对照表里。
# ==============================================================================
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
glc_board_full.py —— **板端单进程跑通整个编码侧**：
    输入图张量 -> S1(NPU) -> 胶水 -> S2(NPU) -> 胶水 -> S3p1/p2/p3(NPU) -> 胶水
    -> 操作数 -> PL rANS -> GLC2 容器

与既有链路的关系：
    board_e2e.py(PC) : PC 用 ssh 驱动板子跑 5 个子图，**胶水层在 PC 的 torch 里**
    glc_e2e.py(板)   : 只做 操作数 -> PL -> 容器（操作数由 PC 产）
    本脚本(板)       : 胶水层也搬到板子上（numpy），**整个编码侧不再碰 PC**

胶水层为什么是这几行（逐行核对源码，不是猜）：
    z_vq.get_indices / get_quan_feat   vqgan_arch.py:97,109   argmin + gather
    separate_prior                     common_model.py:56      chunk(3,1)+clamp_min(0.5)+倒数
    y_spatial_prior_reduction          image_model.py:74       nn.Conv2d(768,256,1)
    get_mask_four_parts                common_model.py:163     纯索引
    process_with_mask                  common_model.py:75      逐元素
    quant                              common_model.py:15      round

⚠️ 唯一有数值归约的一步是那个 1x1 卷积。已实测：numpy 与 torch **不逐位一致**
   （最大绝对差 ~3e-6）。所以本脚本在每一步都跟板端已有的参考做**逐字节**比对，
   把"差异有没有传导下去"用数据回答。

安全：先把参考物（run/ 与 pack/img{0..3}）快照到 /root/glc/ref_stage，
      本脚本的产物一律写到 /root/glc/pack/full_<tag>/，**绝不覆盖参考**。
"""
import argparse
import hashlib
import mmap
import os
import shutil
import struct
import subprocess
import sys
import time

import numpy as np

MODELS = "/root/glc/models"
RUN = "/root/glc/run"
CONSTS = "/root/glc/consts"
PACK = "/root/glc/pack"
REF = "/root/glc/ref_stage"

Z_INDEX_BITS = 14
HEADER_SIZE = 76
SCALE_MIN = np.float32(0.11)

REG_BASE = 0x400C0000
REG_LEN = 0x2000
R_START, R_RBASE32, R_RSIZE, R_WBASE32, R_NSYM = 0x00, 0x0C, 0x10, 0x14, 0x20
R_DONE, R_VER, R_STATUS, R_PLWORDS, R_CYC = 0x80, 0x84, 0x88, 0x8C, 0x98
R_NSYM_R = 0xA4
VER_EXPECT = 0x20260922
HP_CLK_MHZ = 200.0
# ======================================================================
# 尺寸层（2026-10-18）：**256 是出厂默认，行为逐位不变**；512 是预研路径。
#   为什么要有它：512 的 ONNX/五步流水线已经验过（见 `56` §6），但板端的容器、
#   PL 的 DMA 缓冲、NPU 模型都是按 256 写死的。这里把所有尺寸**从 SIZE 推出来**，
#   让 512 至少不再是"散落各处的魔数"。
#   ⚠️ 512 目前**没有上过板**：模型要换 512 版、B 端也要换，所以默认拒绝运行。
# ======================================================================
SIZE = int(os.environ.get('GLC_SIZE', '256'))
if SIZE not in (256, 512):
    raise SystemExit('GLC_SIZE 只能是 256 或 512（收到 %r）' % SIZE)
if SIZE != 256 and os.environ.get('GLC_ALLOW_512', '0') != '1':
    raise SystemExit('GLC_SIZE=512 从未上板验证过（要同时换 512 模型 / PL 缓冲 / B 端）。'
                     '确实要试请再设 GLC_ALLOW_512=1。')
L = SIZE // 16            # 潜伏边长：256→16，512→32
Z = L // 4                # 超先验边长：16→4，32→8
NSYM = L * L * 64         # 每相位符号数 = L² × (256/4)：256→16,384，512→65,536
Z_PAY_BYTES = (Z * Z * Z_INDEX_BITS + 7) // 8   # z 段：16 索引→28 B，64 索引→112 B
OUT_MAX_BYTES = NSYM * 4                        # 每相位最坏输出（4 B/符号）
# PL 一块 DMA 里要放 [输入 in_bytes | 输出 OUT_MAX]，再留 64 KB 余量
CHUNK_BYTES = max(512 * 1024, (NSYM // 16) * 64 + OUT_MAX_BYTES + 64 * 1024)   # 256 沿用历史的 512 KB，512 才需要 576 KB

# 头里那 10 个 u32 的顺序（glc_e2e.py 按同一顺序解）：ORIG_H/W, PAD_H/W, Y_C/H/W, Z_C/H/W
HDR_VALUES = (SIZE, SIZE, SIZE, SIZE, 256, L, L, 256, Z, Z)

# 出厂 256 的自检：任何一个推导错了，这里立刻炸（保护在跑的产线路径）
if SIZE == 256:
    assert (L, Z, NSYM, Z_PAY_BYTES, OUT_MAX_BYTES) == (16, 4, 16384, 28, 65536), \
        '尺寸推导与 256 历史常量不符！' 

GLC_SCALE_BOUND = np.float32(0.109999999)
GLC_SCALE_TABLE = np.array([
    0.109999999, 0.124404095, 0.14069438, 0.159117803,
    0.179953694, 0.203517973, 0.230167925, 0.26030761,
    0.294393927, 0.332943738, 0.376541555, 0.425848305,
    0.481611609, 0.5446769, 0.616000414, 0.696663439,
    0.787889004, 0.891060233, 1.00774133, 1.13970149,
    1.28894126, 1.4577235, 1.64860713, 1.86448622,
    2.108634, 2.38475204, 2.69702673, 3.05019283,
    3.44960451, 3.90131736, 4.41218138, 4.98994064,
    5.64335394, 6.38233089, 7.2180748, 8.16325474,
    9.23220348, 10.4411287, 11.8083563, 13.3546171,
    15.1033554, 17.0810852, 19.3177948, 21.8473892,
    24.7082233, 27.9436817, 31.6028042, 35.7410774,
    40.4212379, 45.7142525, 51.7003784, 58.4703369,
    66.1268311, 74.7859116, 84.5788345, 95.6541443,
    108.179733, 122.345444, 138.366165, 156.484741,
    176.9758, 200.150177, 226.359055, 256,
], dtype=np.float32)

SUBGRAPHS = {
    "s1":   ("s1_encoder_ga_hyper", ["in0.ftmp"], [3310, 3314],
             [(1, L, L, 256), (1, Z, Z, 256)]),
    "s2":   ("s2_hyperdec_fusion",  ["in0.ftmp"], [184], [(1, L, L, 768)]),
    "s3p1": ("s3_phase1", ["in0.ftmp", "in1.ftmp"], [178, 182],
             [(1, L, L, 256), (1, L, L, 256)]),
    "s3p2": ("s3_phase2", ["in0.ftmp", "in1.ftmp"], [178, 182],
             [(1, L, L, 256), (1, L, L, 256)]),
    "s3p3": ("s3_phase3", ["in0.ftmp", "in1.ftmp"], [178, 182],
             [(1, L, L, 256), (1, L, L, 256)]),
}

MASK_TBL = {0: [0, 1, 2, 3], 1: [3, 2, 1, 0], 2: [2, 3, 0, 1], 3: [1, 0, 3, 2]}
MICRO = [np.array([[1, 0], [0, 0]], dtype=np.float32),
         np.array([[0, 1], [0, 0]], dtype=np.float32),
         np.array([[0, 0], [1, 0]], dtype=np.float32),
         np.array([[0, 0], [0, 1]], dtype=np.float32)]

LOG = []


def say(s):
    print(s)
    sys.stdout.flush()
    LOG.append(s)


def md5(b):
    return hashlib.md5(b).hexdigest()


def snapshot():
    """把参考物快照一次，之后本脚本随便覆盖 run/ 都不会丢参考。"""
    if os.path.isdir(REF):
        say("参考快照已存在: %s" % REF)
        return
    os.makedirs(REF)
    shutil.copytree(RUN, REF + "/run")
    for i in range(4):
        d = "%s/img%d" % (PACK, i)
        if os.path.isdir(d):
            shutil.copytree(d, "%s/pack_img%d" % (REF, i))
    say("已建参考快照: %s" % REF)


def report_diff(tag, a, b):
    if a.shape != b.shape:
        say("      [%s] ** 形状不同 %s vs %s **" % (tag, a.shape, b.shape))
        return False
    nd = int((a.reshape(-1) != b.reshape(-1)).sum())
    if nd == 0:
        say("      [%s] 逐位一致  (%s)" % (tag, a.shape))
        return True
    mx = float(np.abs(a.astype(np.float64) - b.astype(np.float64)).max())
    say("      [%s] ** 不一致 ** 不同 %d/%d 个, 最大绝对差 %.3e" % (tag, nd, a.size, mx))
    return False


def nhwc(t):
    return np.ascontiguousarray(t.transpose(0, 2, 3, 1))


def to_nchw(a):
    return np.ascontiguousarray(a.transpose(0, 3, 1, 2))


def build_index(scales):
    """把 scale 映射到码表下标（0..63）。

    ★ 2026-09-23 等价替换：原实现建一个 (N, 63) 的布尔矩阵再 sum(axis=1)。
      每相位 N = 65536/4 = 16384 ⇒ 单相位 103 万个元素的临时数组，
      4 个相位合计每张图 400 万个元素（实测占每张编码时间 ~7%）。

      GLC_SCALE_TABLE[:63] 实测**严格升序**（0.11 → 226.359），因此
          cnt[i] = #{j<63 : TABLE[j] >= sc[i]} = 63 - searchsorted(TABLE[:63], sc[i], "left")
          返回 63 - cnt  ⇒  **恰好等于 searchsorted(TABLE[:63], sc, "left")**
      已用 411,380 个样本（真实 scales + 7 组边界压力）逐元素验证：0 个不等。
      见 工具/板端脚本/verify_build_index.py。
    """
    sc = np.asarray(scales, dtype=np.float32)
    sc = np.where(sc > GLC_SCALE_BOUND, sc, GLC_SCALE_BOUND)
    return np.searchsorted(GLC_SCALE_TABLE[:63], sc, side="left").astype(np.uint32)


def build_header(z_count, zpay_len, stream_lens):
    """装 76 B 头。抽成函数是为了能单测（见 `工具/回归/单元测试_容器头.py`）。

    布局：`GLC2` + ver(B) + q(B) + 保留(H) [8 B]
          + 10 个 u32 = HDR_VALUES [40 B]
          + z_count(u32) + z_len(u32) [8 B]
          + 4 条流长度(u32×4) [16 B]
          + 保留(u32) [4 B]   ⇒ 合计 76 B
    """
    assert len(stream_lens) == 4, '必须正好 4 条 rANS 流'
    hb = struct.pack(">4sBBH", b"GLC2", 2, 0, 0)
    for v in HDR_VALUES:
        hb += struct.pack(">I", int(v))
    hb += struct.pack(">I", int(z_count))
    hb += struct.pack(">I", int(zpay_len))
    for k in range(4):
        hb += struct.pack(">I", int(stream_lens[k]))
    hb += struct.pack(">I", 0)
    assert len(hb) == HEADER_SIZE, len(hb)
    return hb


def pack_fixed_width(values, bit_width):
    limit = 1 << bit_width
    acc = 0
    nb = 0
    out = bytearray()
    for v in values:
        v = int(v)
        if v < 0 or v >= limit:
            raise ValueError("z index %d 超出 %d bit" % (v, bit_width))
        acc = (acc << bit_width) | v
        nb += bit_width
        while nb >= 8:
            nb -= 8
            out.append((acc >> nb) & 0xFF)
            acc &= (1 << nb) - 1 if nb else 0
    if nb:
        out.append((acc << (8 - nb)) & 0xFF)
    return bytes(out)


def make_masks(C, H, W):
    base = [np.tile(mm, ((H + 1) // 2, (W + 1) // 2))[:H, :W] for mm in MICRO]
    out = []
    for k in range(4):
        groups = [np.tile(base[j], (C // 4, 1, 1)) for j in MASK_TBL[k]]
        out.append(np.concatenate(groups, axis=0).reshape(1, C, H, W))
    return out


def compact(t, mask_bool):
    b, c, h, w = t.shape
    return t[np.broadcast_to(mask_bool, t.shape)].reshape(1, c, h, w // 4)


def run_npu(key, cwd):
    name, in_files, vids, shapes = SUBGRAPHS[key]
    if os.path.isdir(cwd + "/logs"):
        shutil.rmtree(cwd + "/logs")
    os.makedirs(cwd + "/logs")
    cmd = ["/usr/bin/icraft-run",
           "--json", "%s/%s_ZG.json" % (MODELS, name),
           "--raw", "%s/%s_ZG.raw" % (MODELS, name),
           "--input", ";".join(in_files),
           "--backends", "ZG330,axi://zg330aiu;Host",
           "--log_path", "logs", "--log_time", "--ocmopt", "1",
           "--dump_format", "SFB", "--dump_ftmp", ",".join(str(v) for v in vids)]
    t0 = time.perf_counter()
    p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, universal_newlines=True)
    wall = time.perf_counter() - t0
    hard = float("nan")
    for ln in p.stdout.splitlines():
        if "total_hard_time:" in ln:
            try:
                hard = float(ln.split("total_hard_time:")[1].split()[0])
            except Exception:
                pass
    outs = []
    for v, shp in zip(vids, shapes):
        fp = "%s/logs/%s/ftmpSFB/%d.ftmp" % (cwd, name, v)
        if not os.path.exists(fp):
            say("   !! 缺输出 %s" % fp)
            say(p.stdout[-1500:])
            raise SystemExit(5)
        outs.append(to_nchw(np.fromfile(fp, dtype=np.float32).reshape(shp)))
    say("   NPU %-5s rc=%d hard=%s ms  wall=%.0f ms"
        % (key, p.returncode, ("%.3f" % hard) if hard == hard else "?", wall * 1000))
    return outs, hard, wall


class RegWin(object):
    def __init__(self):
        self.fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        self.mm = mmap.mmap(self.fd, REG_LEN, mmap.MAP_SHARED,
                            mmap.PROT_READ | mmap.PROT_WRITE, offset=REG_BASE)

    def rd(self, off):
        return struct.unpack_from("<I", self.mm, off)[0]

    def wr(self, off, v):
        struct.pack_into("<I", self.mm, off, v & 0xFFFFFFFF)


def pl_encode(op_dir, rbase, chunk, reg):
    streams = []
    cyc_total = 0
    for k in range(4):
        sym = np.fromfile("%s/p%d_sym.i32" % (op_dir, k), dtype=np.int32)
        scl = np.fromfile("%s/p%d_scales.f32" % (op_dir, k), dtype=np.float32)
        N = sym.size
        nbeat = (N + 15) // 16
        in_bytes = nbeat * 64
        out_off = in_bytes
        ki = build_index(scl)
        w = ((sym.astype(np.uint32) & 0xFFFF) << 16) | (ki & 0x3F)
        send = np.zeros(in_bytes + OUT_MAX_BYTES, dtype=np.uint8)
        send[:N * 4] = w.view(np.uint8)
        chunk.write(0, send.tobytes(), send.size)
        reg.wr(R_RBASE32, rbase)
        reg.wr(R_RSIZE, nbeat)
        reg.wr(R_WBASE32, rbase + out_off)
        reg.wr(R_NSYM, N)
        reg.wr(R_START, 1)
        for _ in range(20000000):
            if reg.rd(R_DONE) & 1:
                break
        plw = reg.rd(R_PLWORDS) & 0xFFFF
        cyc = reg.rd(R_CYC)
        cyc_total += cyc
        raw = bytearray(plw * 4)
        chunk.read(raw, out_off, plw * 4)
        streams.append(bytes(raw))
        say("   PL  phase %d: %6d 符号 -> %4d B  cyc=%d  nsym_rb=%d"
            % (k, N, plw * 4, cyc, reg.rd(R_NSYM_R) & 0xFFFF))
    return streams, cyc_total


# ---------------------------------------------------------------- 常量缓存
# ★ 2026-10-17 提速：`codebook`（16384×256）、`ysp_reduce_w/b` 原来在 main() 里
#   **每张图都 np.load 一遍**。cProfile 实测这 3 次 load 共 **73 ms/张**
#   （其中 codebook 的 npy 就有 16 MB）。
#   常驻 daemon 里这些常量永不变化 ⇒ 进程内缓存一次即可。
#   安全性：三者在 main() 里都是**只读**用法（`codebook**2`、`zz @ codebook.T`、
#   1×1 conv 的权重/偏置），没有任何原地修改，所以缓存不会串味。
_CONSTS = {}


def load_consts():
    # 用 'codebook' 是否存在来判断，不用 `if not _CONSTS` —— 否则将来谁先调了别的
    # 缓存函数（比如 load_masks），_CONSTS 非空就会跳过三份常量的加载。
    if 'codebook' not in _CONSTS:
        _CONSTS['codebook'] = np.load(CONSTS + "/z_codebook.npy")
        _CONSTS['ysp_w'] = np.load(CONSTS + "/ysp_reduce_w.npy").reshape(256, 768)
        _CONSTS['ysp_b'] = np.load(CONSTS + "/ysp_reduce_b.npy")
    return _CONSTS['codebook'], _CONSTS['ysp_w'], _CONSTS['ysp_b']


# ★ 2026-10-17 提速（胶水拆解实测之后）：把"每帧都在重算、但其实只依赖上面那几个常量"
#   的派生量也算一次。拆解结果（附八）：`(codebook**2).sum(1)` 每帧 **26.0 ms**
#   —— 4.2M 个元素平方再按行求和，还要多分配一个 16 MB 的临时数组；
#   `ysp_w -> float64` 每帧 0.9 ms + 1.5 MB 分配。两个都是**纯函数**。
#   安全性：同一份输入、同一个 numpy 操作 ⇒ 结果**逐位相同**（不是"差不多"），
#   10 张图容器 md5 逐个相同是硬验收。三者都是只读用法，缓存不会串味。
def load_derived():
    if 'cb2' not in _CONSTS:
        cb, w, _ = load_consts()
        _CONSTS['cb2'] = (cb ** 2).sum(1)
        _CONSTS['ysp_w64'] = w.astype(np.float64)
    return _CONSTS['cb2'], _CONSTS['ysp_w64']


def load_masks(C=256, H=L, W=L):
    """masks / mask_bool 只依赖 (C,H,W)，每帧重算约 2~3 ms，同样缓存。只读用法。"""
    key = ('masks', C, H, W)
    if key not in _CONSTS:
        m = make_masks(C, H, W)
        _CONSTS[key] = (m, [x.astype(bool) for x in m])
    return _CONSTS[key]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    # ★★ 2026-10-17：`LOG` 是**模块级**的、`say()` 只往里追加；而结尾会把整份 LOG
    #   写进 `pack/full_<tag>.log`。单张跑没问题；但常驻 daemon 里 `main()` 被反复调用
    #   ⇒ LOG **永不清理、越攒越长、而且每帧把累积的全量重写一遍到 SD**。
    #   实测（160 帧后）：`full_img0.log` 已 5,440 行 / 255 KB ⇒ 每帧往 eMMC 白写 255 KB，
    #   而且这个数字随帧数线性增长（跑到 5,000 帧就是 ~8 MB/帧，那时每帧要多几百毫秒 + 磨闪存）。
    #   在 main() 开头清空：那份文件本来就应该只记"这一次编码"。
    del LOG[:]
    tag = "img%d" % a.sample
    ref_op = "%s/pack_%s" % (REF, tag)
    my_op = "%s/full_%s" % (PACK, tag)
    out_path = a.out or ("%s/full_%s.glc" % (PACK, tag))
    ref_glc = "%s/%s.glc" % (PACK, tag)

    say("############ 板端全链路编码（单进程） sample=%d ############" % a.sample)
    snapshot()
    os.makedirs(my_op, exist_ok=True)

    codebook, ysp_w, ysp_b = load_consts()
    cb2, ysp_w64 = load_derived()
    say("常量: codebook %s  ysp_w %s  (已缓存，首次 load 后不再重读；cb2/ysp_w64 同)" % (codebook.shape, ysp_w.shape))

    npu_hard = 0.0
    npu_wall = 0.0
    t_all = time.perf_counter()

    # ---------- S1 ----------
    say("\n[1/6] S1 (NPU)  输入 = %s/s1/in0.ftmp" % RUN)
    (y, z), hard, wall = run_npu("s1", "%s/s1" % RUN)
    npu_hard += hard
    npu_wall += wall
    say("      y%s  z%s" % (y.shape, z.shape))

    # ---------- z_vq ----------
    say("\n[2/6] 胶水 z_vq (argmin + gather)")
    zz = np.ascontiguousarray(z.transpose(0, 2, 3, 1)).reshape(-1, codebook.shape[1])
    d = (zz ** 2).sum(1, keepdims=True) + cb2[None, :] - 2.0 * (zz @ codebook.T)
    z_idx = np.argmin(d, axis=1).astype(np.int32)
    if os.environ.get('GLC_VERBOSE_DIFF', '0') == '1':
        ref_zidx = np.fromfile("%s/z_indices.i32" % ref_op, dtype=np.int32)
        say("      本脚本 = %s" % z_idx.tolist())
        say("      参考   = %s" % ref_zidx.tolist())
        say("      -> %s" % ("**一致**" if np.array_equal(z_idx, ref_zidx) else "**不同**"))
    z_hat_nhwc = codebook[z_idx].reshape(1, Z, Z, 256).astype(np.float32)
    if os.environ.get('GLC_VERBOSE_DIFF', '0') == '1':
        staged = np.fromfile("%s/run/s2/in0.ftmp" % REF, dtype=np.float32).reshape(1, Z, Z, 256)
        report_diff("s2 输入(z_hat) vs 上次链路staged", z_hat_nhwc, staged)

    # ---------- S2 ----------
    say("\n[3/6] S2 (NPU)")
    z_hat_nhwc.tofile("%s/s2/in0.ftmp" % RUN)
    (params,), hard, wall = run_npu("s2", "%s/s2" % RUN)
    npu_hard += hard
    npu_wall += wall

    say("\n[4/6] 胶水 separate_prior + y_spatial_prior_reduction(1x1 conv)")
    quant_step, scales0, means0 = np.split(params, 3, axis=1)
    qs = np.maximum(quant_step, np.float32(0.5))
    q_enc = (np.float32(1.0) / qs).astype(np.float32)
    q_dec = qs.astype(np.float32)
    # ⚠️ 这个 1x1 卷积是整条胶水里**唯一有数值归约**的一步，而它必须与 PC 解码侧
    #    **逐位一致**（容器不存 scales/means，解码侧要重推）。实测：fp32 下
    #    板端 numpy(aarch64 BLAS) 与 PC numpy(x86 BLAS)/torch 的末位差可达 7.9e-07，
    #    经 S3 的 INT8 量化边界放大后会让个别样本（实测样本 3）解不出来。
    #    => 用 **float64 累加后再转回 float32**，把 BLAS 后端依赖压到可忽略。
    common = (ysp_w64 @ params.reshape(768, -1).astype(np.float64)
              + ysp_b.astype(np.float64)[:, None]).astype(np.float32)
    common = common.reshape(1, 256, L, L)
    if os.environ.get('GLC_VERBOSE_DIFF', '0') == '1':
        staged_c = np.fromfile("%s/run/s3p1/in1.ftmp" % REF, dtype=np.float32).reshape(1, L, L, 256)
        report_diff("common vs 上次链路staged", nhwc(common), staged_c)

    # ---------- 四相位 ----------
    say("\n[5/6] 四相位 S3p1/2/3 (NPU) + 胶水")
    C, H, W = 256, L, L
    masks, mask_bool = load_masks(C, H, W)
    y_scaled = (y * q_enc).astype(np.float32)
    y_hat_so_far = np.zeros((1, C, H, W), dtype=np.float32)

    sym_same = 0
    scl_same = 0
    for k in range(4):
        if k == 0:
            s_raw, m_raw = scales0, means0
        else:
            key = "s3p%d" % k
            if os.environ.get('GLC_VERBOSE_DIFF', '0') == '1':
                if k == 1:
                    st = np.fromfile("%s/run/s3p1/in0.ftmp" % REF,
                                     dtype=np.float32).reshape(1, 16, 16, 256)
                    report_diff("phase0 后 y_hat_so_far vs 上次链路staged", nhwc(y_hat_so_far), st)
            nhwc(y_hat_so_far).tofile("%s/%s/in0.ftmp" % (RUN, key))
            nhwc(common).tofile("%s/%s/in1.ftmp" % (RUN, key))
            (s_raw, m_raw), hard, wall = run_npu(key, "%s/%s" % (RUN, key))
            npu_hard += hard
            npu_wall += wall

        means_hat = (m_raw * masks[k]).astype(np.float32)
        y_res = ((y_scaled - means_hat) * masks[k]).astype(np.float32)
        y_q = np.round(y_res).astype(np.float32)
        y_hat = (y_q + means_hat).astype(np.float32)
        y_hat_so_far = (y_hat_so_far + y_hat).astype(np.float32)

        yv = compact(y_scaled, mask_bool[k])
        sm = np.maximum(compact(s_raw, mask_bool[k]), SCALE_MIN).astype(np.float32)
        mn = compact(m_raw, mask_bool[k]).astype(np.float32)
        sym = np.round(yv - mn).astype(np.int32).reshape(-1)

        s_raw.reshape(-1).astype(np.float32).tofile("%s/p%d_scales_raw.f32" % (my_op, k))
        m_raw.reshape(-1).astype(np.float32).tofile("%s/p%d_means_raw.f32" % (my_op, k))
        sym.tofile("%s/p%d_sym.i32" % (my_op, k))
        sm.reshape(-1).astype(np.float32).tofile("%s/p%d_scales.f32" % (my_op, k))

        if os.environ.get('GLC_VERBOSE_DIFF', '0') == '1':
            rsym = np.fromfile("%s/p%d_sym.i32" % (ref_op, k), dtype=np.int32)
            rsm = np.fromfile("%s/p%d_scales.f32" % (ref_op, k), dtype=np.float32)
            ns = int((sym != rsym).sum())
            nc = int((sm.reshape(-1) != rsm).sum())
            sym_same += (ns == 0)
            scl_same += (nc == 0)
            say("   phase %d: %6d 符号 | sym %s (差 %d) | scales %s (差 %d)"
                % (k, sym.size, "一致" if ns == 0 else "不同", ns,
                   "一致" if nc == 0 else "不同", nc))
        else:
            say("   phase %d: %6d 符号 (参考对比已关，置 GLC_VERBOSE_DIFF=1 可开)" % (k, sym.size))
    say("   操作数 vs PC 链路参考: sym %d/4 一致, scales %d/4 一致" % (sym_same, scl_same))
    z_idx.tofile("%s/z_indices.i32" % my_op)

    # ---------- PL ----------
    say("\n[6/6] PL rANS + 组装 GLC2 容器")
    import icraft.xrt as xrt
    dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
    chunk = dev.defaultMemRegion().malloc(CHUNK_BYTES, False, 64)   # 512 尺寸下 512 KB 不够
    rbase = chunk.begin.addr()
    reg = RegWin()
    v84 = reg.rd(R_VER)
    say("   chunk=0x%X  +0x84=0x%08X (期望 0x%08X)" % (rbase, v84, VER_EXPECT))
    if v84 != VER_EXPECT:
        say("*** PL 指纹不对，拒绝继续 ***")
        return 3
    streams, cyc_total = pl_encode(my_op, rbase, chunk, reg)

    zpay = pack_fixed_width(np.fromfile("%s/z_indices.i32" % my_op, dtype=np.int32).tolist(),
                            Z_INDEX_BITS)
    hb = build_header(z_idx.size, len(zpay), [len(x) for x in streams])
    blob = hb + zpay + b"".join(streams)
    open(out_path, "wb").write(blob)

    total_ms = (time.perf_counter() - t_all) * 1000.0
    say("\n================ 板端全链路结果 ================")
    say("  尺寸 %d×%d（潜伏 %d×%d，z %d×%d，每相位 %d 符号，z 段 %d B）"
        % (SIZE, SIZE, L, L, Z, Z, NSYM, len(zpay)))
    say("  容器 %s : %d B  md5=%s" % (out_path, len(blob), md5(blob)))
    say("  NPU 硬计算合计(total_hard_time) : %.3f ms" % npu_hard)
    say("  NPU 进程墙钟合计                : %.0f ms" % (npu_wall * 1000))
    say("  PL rANS 实测                    : %d 拍 = %.3f ms @200MHz"
        % (cyc_total, cyc_total / HP_CLK_MHZ / 1000.0))
    say("  编码侧整链路墙钟                : %.1f ms" % total_ms)
    say("  bpp: payload %d B -> %.6f ; 整容器 %d B -> %.6f"
        % (sum(len(s) for s in streams), 8.0 * sum(len(s) for s in streams) / 65536.0,
           len(blob), 8.0 * len(blob) / 65536.0))

    if os.path.exists(ref_glc):
        ref = open(ref_glc, "rb").read()
        say("\n  参考(PC 链路) %s : %d B md5=%s" % (ref_glc, len(ref), md5(ref)))
        if ref == blob:
            say("  ==> **板端全链路容器 == PC 链路容器，逐字节一致**")
        else:
            zend = HEADER_SIZE + len(zpay)
            n = min(len(ref), len(blob))
            i = 0
            while i < n and ref[i] == blob[i]:
                i += 1
            say("  ==> 与 PC 链路容器**有差异**：长度 %d vs %d，首个不同字节 @%d"
                % (len(blob), len(ref), i))
            say("      头段 %s / z段 %s / 流段 %s"
                % ("OK" if ref[:HEADER_SIZE] == blob[:HEADER_SIZE] else "差异",
                   "OK" if ref[HEADER_SIZE:zend] == blob[HEADER_SIZE:zend] else "差异",
                   "OK" if ref[zend:] == blob[zend:] else "差异"))

    open("%s/full_%s.log" % (PACK, tag), "w").write("\n".join(LOG) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
