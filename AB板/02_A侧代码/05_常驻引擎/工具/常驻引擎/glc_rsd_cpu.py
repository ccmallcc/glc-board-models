#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""glc_rsd_cpu.py —— 常驻路径下用 **A53 CPU 的 glc2_pack** 替代 PL rANS
（GLC 2026-10-09）

为什么这么做
------------
常驻引擎（`glc_rsd.py`）单张已经验证正确且快 12 倍（0.783 s/帧），但**批量连编时容器不符**。
排查出两个互相纠缠的疑点，都出在 `glc_board_full.py` 的 `[6/6]` PL 段：

  1. 那段里**每次编码一张图就再 `xrt.Device.Open` 一次同一个 NPU**（+ 从默认内存区
     `malloc(512*1024)`，从不释放），会把常驻 Session 依赖的 DMA 状态打乱；
  2. `RegWin()` **每次都新开 `/dev/mem` + mmap，从不关闭**。

而 `pack_full.sh` 早就实测证明：**PL rANS 与 A53 CPU 的 `glc2_pack` 产出逐字节一致**，
而 CPU 只要 **35 ms**。⇒ **常驻路径干脆不用 PL 段**，这两个疑点一起消失。

本模块做三件事（全部是 monkeypatch，不改 `glc_board_full.py` 一行）
--------------------------------------------------------------
  A. `pl_encode`      → `pl_encode_cpu`：调 `glc2_pack` 产容器，再从头里反解出 4 条码流
  B. `RegWin`         → `StubRegWin`：**完全不碰 /dev/mem**，只回答指纹查询
  C. `xrt.Device.Open`→ 全进程**只真开一次**设备句柄（复用给常驻引擎）

关于 B 的诚实说明
----------------
`glc_board_full.py` 用 `reg.rd(R_VER) != 0x20260922` 来确认"PL 里是我们那条 rANS 位流"，
不对就 `return 3` 拒绝继续。**这条检查是为了保护 PL 通路**。既然本路径**根本不用 PL 通路**，
这个前置条件就不成立了 ⇒ 用桩件直接回答"指纹正确"是**语义上正确**的，但**必须写明**：
**本路径不依赖任何自定义位流，官方位流也能跑**（这正是它的好处之一）。
代价：日志里那行 `PL rANS 实测: N 拍` 会变成 0 —— 因为确实没用 PL。

自检
----
`pl_encode_cpu` 会**自己重建一遍容器头**并与 `glc2_pack` 的产物逐字节比对，
不一致就报错 —— 这样"反解码流"这一步出错不会静默传下去。
"""
import os
import re
import struct
import subprocess
import time

import numpy as np

GLC2_PACK = "/root/glc/pack/glc2_pack"
REF = "/root/glc/ref_stage"
HEADER_SIZE = 76

_G = None                       # 由 patch() 注入 glc_board_full 模块
STAT = {"frames": 0, "pack_calls": 0, "t_total": 0.0, "t_probe": 0.0, "t_final": 0.0,
        "rounds": 0, "exact": 0, "skip_final": 0, "sem": "-"}

# --------------------------------------------------- 跨帧提示（候选 #1，2026-10-17）
#   `pl_encode_cpu` 是"探长度再定稿"的收敛循环，一轮只能学到一个相位（原因见函数里的注释）。
#   画面不变 / 相邻帧相近时，4 个相位长度**完全一样**，所以把上一帧的值当初始值，
#   命中几个前缀相位就省几轮。探针 5 轮 → 1 轮；连定稿一起，6 次起进程 → 1 次。
_HINT = [0, 0, 0, 0]            # 上一帧成功收敛到的 4 个相位长度
_HMAX = 65536                   # 大于理论上限（16384 符号 × 2 B = 32768），真值不可能等于它
_SEM = None                     # None=未探测 / "real"=报真值 / "pad"=会把 STAGE_LEN 当长度填充


# ----------------------------------------------------------------- 小工具
def _hdr_path(d):
    return os.path.join(d, "hdr.txt")


def _ensure_hdr(d):
    """hdr.txt 不在就从 ref_stage 拷一份，并把 4 个 STAGE 长度清零（与 pack_full.sh 同做法）。"""
    p = _hdr_path(d)
    if os.path.exists(p):
        return p
    src = "%s/pack_img0/hdr.txt" % REF
    if not os.path.exists(src):
        raise RuntimeError("既没有 %s，也找不到参考模板 %s" % (p, src))
    with open(src) as f:
        txt = f.read()
    txt = re.sub(r"^STAGE(\d)_LEN .*$", lambda m: "STAGE%s_LEN 0" % m.group(1), txt, flags=re.M)
    with open(p, "w") as f:
        f.write(txt)
    return p


def _set_stage_len(d, k, n):
    p = _ensure_hdr(d)
    with open(p) as f:
        txt = f.read()
    new = re.sub(r"^STAGE%d_LEN .*$" % k, "STAGE%d_LEN %d" % (k, n), txt, flags=re.M)
    if new == txt and ("STAGE%d_LEN %d" % (k, n)) not in txt:
        print("   !! hdr.txt 里没有 STAGE%d_LEN 这一行，无法写入" % k)
    with open(p, "w") as f:
        f.write(new)


def _run_pack(d, out):
    # ★ 先删旧产物：让"文件存在"严格等于"这一轮真的写成功了"。
    #   否则某一轮失败时会捡到**上一帧**的同名残留文件（`/tmp/_rsd_*.glc` 是固定路径）。
    try:
        os.remove(out)
    except OSError:
        pass
    t0 = time.time()
    r = subprocess.run([GLC2_PACK, d, out], stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, universal_newlines=True)
    STAT["pack_calls"] += 1
    return r.stdout, (time.time() - t0)


def _parse_lens(txt):
    lens = []
    for k in range(4):
        m = re.search(r"phase\s+%d\s*:.*?->\s*(\d+)\s*B" % k, txt, re.M)
        lens.append(int(m.group(1)) if m else None)
    return lens


# ----------------------------------------------------------------- A. pl_encode 的 CPU 版
def pl_encode_cpu(op_dir, rbase=None, chunk=None, reg=None):
    """与 glc_board_full.pl_encode 同签名同返回值：(streams, cyc_total)。

    ★ 不碰 rbase/chunk/reg —— 那三个参数只为兼容签名而保留。
    """
    global _SEM            # 语义探测结果要跨帧记住；不写会变成局部变量（UnboundLocalError）
    t_all = time.time()
    _ensure_hdr(op_dir)

    # ---- ★ 探针初值 = 上一帧的长度（候选 #1，2026-10-17）----
    #   【老结论，2026-10-09 记的】"`glc2_pack` 报的相位长度 = max(真实, STAGE_LEN)，会把码流
    #   填充到 STAGE_LEN；从偏大初值出发会收敛到**错误的稳定点**，而且日志上全是对勾"
    #   ⇒ 所以原来每帧都先清零，只敢从"偏小"起步。
    #
    #   ★ 2026-10-17 在同一块板、同一个二进制上实测，**推翻**了上面的机制（3 组偏大初值）：
    #       真值 [60,60,48,44]，hdr 写 [56,…] -> "phase 0: -> 60 B (参考 56) ❌"
    #       真值 [60,60,48,44]，hdr 写 [65,…] -> "phase 0: -> 60 B (参考 65) ❌"
    #       真值 [60,60,48,44]，hdr 写 [90×4] -> "phase 0: -> 60 B (参考 90) ❌"
    #     三组都**报真值**、都**不写容器**。⇒ 没有任何"填充到 STAGE_LEN"，STAGE_LEN 只是断言。
    #   ⇒ 偏大**不会**毒化收敛（下一轮就会被纠正）；真正决定探针次数的是另一件事：
    #     **它遇到第一个断言不符就退出**，所以一轮探针只能学到"第一个不符的相位"。
    #   ⇒ 于是把上一帧的长度当初始值就是纯赚：命中几个前缀相位就省几轮探针。
    #
    #   安全兜底（万一二进制将来被换掉、真的会填充）：第一次先写 _HMAX（比值上限 32768 还大）。
    #   "填充"语义下它会把 _HMAX 原样当 ✅ 报回来 ⇒ 立刻判定 _SEM="pad" ⇒ 永久退回全 0 起步
    #   （老行为：慢，但不可能有错的稳定点）。这个探测在"报真值"语义下零额外开销 ——
    #   它顺带就报出了 phase 0 的真值，和从 0 起步是同一轮。
    if _SEM is None:
        init = [_HMAX] * 4
    elif _SEM == "pad":
        init = [0, 0, 0, 0]
    else:
        init = list(_HINT)
    lens = list(init)
    for k in range(4):
        _set_stage_len(op_dir, k, lens[k])

    tp0 = time.time()
    rounds = 0
    for _it in range(10):
        txt, _ = _run_pack(op_dir, "/tmp/_rsd_probe.glc")
        rounds += 1
        m = _parse_lens(txt)                 # 允许 None：它遇到第一个长度不符就停
        if all(v is None for v in m):
            raise RuntimeError("glc2_pack 一个相位长度都没打印，输出尾部：\n%s" % txt[-900:])
        if _SEM is None and rounds == 1:
            if all(v == _HMAX for v in m):
                _SEM = "pad"
                print("   !! glc2_pack 语义探测：STAGE_LEN 被当成填充长度（4 个相位都把 %d 当对勾）"
                      " ⇒ 永久退回全 0 起步" % _HMAX)
                lens = [0, 0, 0, 0]
                for k in range(4):
                    _set_stage_len(op_dir, k, 0)
                rounds = 0                   # 这一轮是白跑的，不算
                continue
            _SEM = "real"
        changed = False
        for k, v in enumerate(m):
            if v is not None and v != lens[k]:
                lens[k] = v
                _set_stage_len(op_dir, k, v)
                changed = True
        if not changed and all(v is not None for v in m):
            break                            # 四相位齐全且稳定 -> 收敛
    STAT["t_probe"] += time.time() - tp0
    STAT["rounds"] += rounds
    if rounds == 1:
        STAT["exact"] += 1
    STAT["sem"] = str(_SEM)
    if any(v == 0 for v in lens):
        raise RuntimeError("相位长度收敛失败，lens=%s" % lens)

    # ---- 定稿 ----
    #   ★ 若第 1 轮探针就四相位全对，那轮的产物**已经是一份完整合法的容器**
    #     （断言全过它才写文件；`_run_pack` 每轮先删旧文件 ⇒ "存在" = 本轮刚写的）
    #     ⇒ 直接当定稿用，再省掉一次起进程（画面不变时就是这条路径）。
    tf0 = time.time()
    final = "/tmp/_rsd_final.glc"
    if rounds == 1 and _SEM == "real" and os.path.exists("/tmp/_rsd_probe.glc"):
        final = "/tmp/_rsd_probe.glc"
        txt = "(复用第 1 轮探针产物，未再起进程)"
        STAT["skip_final"] += 1
    else:
        txt, _ = _run_pack(op_dir, final)
    STAT["t_final"] += time.time() - tf0
    if not os.path.exists(final):
        raise RuntimeError("glc2_pack 没产出容器：\n%s" % txt[-900:])
    blob = open(final, "rb").read()

    # ---- 从容器头里反解各段长度（头格式与 glc_board_full 的装配完全一致，已由 cmp 验证）----
    zlen = struct.unpack(">I", blob[52:56])[0]
    slens = [struct.unpack(">I", blob[56 + 4 * k:60 + 4 * k])[0] for k in range(4)]
    if slens != lens:
        raise RuntimeError("容器头长度 %s 与收敛得到的 %s 不一致" % (slens, lens))
    off = HEADER_SIZE + zlen
    streams = []
    for L in slens:
        streams.append(blob[off:off + L])
        off += L
    if off != len(blob):
        raise RuntimeError("反解长度不符：解到 %d B，容器实际 %d B（zlen=%d slens=%s）"
                           % (off, len(blob), zlen, slens))

    # ---- ★ 自检：自己重建一遍容器，必须与 glc2_pack 的产物逐字节相同 ----
    if _G is not None:
        try:
            z_idx = np.fromfile("%s/z_indices.i32" % op_dir, dtype=np.int32)
            zpay = _G.pack_fixed_width(z_idx.tolist(), _G.Z_INDEX_BITS)
            if zpay != blob[HEADER_SIZE:HEADER_SIZE + zlen]:
                raise RuntimeError("zpay 段与 glc2_pack 的不一致（%d vs %d B）" % (len(zpay), zlen))
            hb = struct.pack(">4sBBH", b"GLC2", 2, 0, 0)
            for v in (256, 256, 256, 256, 256, 16, 16, 256, 4, 4):
                hb += struct.pack(">I", v)
            hb += struct.pack(">I", int(z_idx.size))
            hb += struct.pack(">I", len(zpay))
            for k in range(4):
                hb += struct.pack(">I", len(streams[k]))
            hb += struct.pack(">I", 0)
            rebuilt = hb + zpay + b"".join(streams)
            if rebuilt != blob:
                raise RuntimeError("重建容器与 glc2_pack 产物不一致（%d vs %d B）"
                                   % (len(rebuilt), len(blob)))
            chk = "深比对通过(头+zpay+4流 逐字节同)"
        except AttributeError as e:
            chk = "跳过深比对(%s)" % e
    else:
        chk = "跳过深比对(未注入模块)"

    dt = time.time() - t_all
    STAT["frames"] += 1
    STAT["t_total"] += dt
    _HINT[:] = lens                        # 只有走到这里（校验全过）才更新提示
    print("   CPU glc2_pack  相位长度=%s  合计 %d B  探针 %d 轮  用时 %.1f ms  [%s]"
          % (slens, sum(slens), rounds, dt * 1000.0, chk))
    return streams, 0


# ----------------------------------------------------------------- B. RegWin 桩件
class StubRegWin(object):
    """替代 glc_board_full.RegWin：**不碰 /dev/mem**，只让指纹检查通过。

    为什么可以这样：本路径用 CPU 打包，**根本不使用 PL 通路**，
    所以"PL 里是不是 rANS 位流"这个前置条件不适用。
    """

    _n = 0                         # 构造次数（原来是 append 到 list，常驻进程里只增不减）

    def __init__(self, *a, **kw):
        StubRegWin._n += 1

    def rd(self, off):
        if _G is not None and off == _G.R_VER:
            return _G.VER_EXPECT
        return 0

    def wr(self, off, val):
        return None


# ----------------------------------------------------------------- C. 设备只开一次
_DEV = None
_ORIG_OPEN = None
_REG = None                     # RegWin 单例（PL 模式）：/dev/mem 每帧 open+mmap 会漏 fd/mmap


def _open_once(url):
    global _DEV
    if _DEV is None:
        _DEV = _ORIG_OPEN(url)
        print("### [patch] xrt.Device.Open 首次真开：%s" % url)
    return _DEV


def patch(G, use_pl=None):
    """把补丁打到 glc_board_full 模块上。返回一个可打印的摘要。

    ★ 2026-10-17 起 `GLC_PL` 决定走哪条打包路（默认 **1 = 真 PL / FPGA rANS**）：
      * `GLC_PL=1`（默认）：**保留** `glc_board_full.pl_encode`（真 PL rANS）+ 真 `RegWin`，
        只接管 `xrt.Device.Open`（全进程只开一次）和 `RegWin`（单例，见下）。
        依据：`工具/常驻引擎/glc_batch_rsd.py` 早就是这么接的，且批量里容器逐字节一致 ——
        "PL 段只是拿它 malloc 一块 512 KB 缓冲区 + 读写寄存器，复用句柄完全等价"。
        ⇒ PL 是项目硬要求（E2/E3），UI 发图这条路**必须**用上 FPGA，不能只图省事走 CPU 打包。
      * `GLC_PL=0`：退回原行为（`pl_encode` → CPU `glc2_pack`，`RegWin` → 桩件）。
        留这个开关，是为了"位流没烧 / PL 指纹不对"时还能出图。
    """
    global _G, _ORIG_OPEN, _REG
    _G = G
    if use_pl is None:
        use_pl = os.environ.get('GLC_PL', '1') != '0'
    import icraft.xrt as _xrt

    applied = []
    if use_pl:
        _RealRegWin = G.RegWin

        def _reg_once(*a, **kw):
            global _REG
            if _REG is None:
                _REG = _RealRegWin(*a, **kw)
            return _REG

        G.RegWin = _reg_once
        applied.append("pl_encode -> 真 PL rANS（FPGA）")
        applied.append("RegWin -> 单例（/dev/mem 只 open+mmap 一次，防 fd/mmap 泄漏）")
    else:
        G.pl_encode = pl_encode_cpu
        applied.append("pl_encode -> CPU glc2_pack（GLC_PL=0）")
        G.RegWin = StubRegWin
        applied.append("RegWin -> 桩件(不碰 /dev/mem)")

    _ORIG_OPEN = _xrt.Device.Open
    try:
        _xrt.Device.Open = staticmethod(_open_once)
        applied.append("xrt.Device.Open -> 全进程只开一次")
    except Exception as e:
        applied.append("xrt.Device.Open 接管失败(%s)" % e)
    return applied


def summary():
    return ("  CPU 打包汇总：%d 帧，glc2_pack 调用 %d 次，打包合计 %.1f ms（平均 %.1f ms/帧）"
            "\n     其中探长 %.1f ms / 定稿 %.1f ms；RegWin 桩件构造 %d 次（未开 /dev/mem）"
            "\n     探针共 %d 轮（%.2f 轮/帧）；提示全中 %d 帧；复用探针产物省掉定稿 %d 帧；"
            "STAGE_LEN 语义=%s"
            % (STAT["frames"], STAT["pack_calls"], STAT["t_total"] * 1000.0,
               (STAT["t_total"] / STAT["frames"] * 1000.0) if STAT["frames"] else 0.0,
               STAT["t_probe"] * 1000.0, STAT["t_final"] * 1000.0, StubRegWin._n,
               STAT["rounds"],
               (float(STAT["rounds"]) / STAT["frames"]) if STAT["frames"] else 0.0,
               STAT["exact"], STAT["skip_final"], STAT["sem"]))
