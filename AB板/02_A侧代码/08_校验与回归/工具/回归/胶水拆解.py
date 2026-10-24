#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""胶水拆解.py —— 把单张编码里那 ~139 ms"胶水"拆到段（**在板子上跑**）

为什么要这么干
--------------
`main()` 里"胶水"= 扣掉 NPU 与 `pl_encode` 之后的一切。它是一条直线代码，
只有插桩才能说清钱花在哪。做法：**读板上正在跑的那份源码**，按锚点插 `_T()`，
写成 `glc_board_full_t.py` 再跑 —— 所以拆的永远是当前部署版本，不存在"拆了另一份"。

插桩只做两件事：加计时、把两处多行表达式按**原求值顺序**拆开（`(a+b)-c` → `a+b` 再 `-c`），
所以产物必须与不插桩时**逐字节相同**（本脚本会顺手把 md5 打出来，可与已知值对比）。

运行前提：**daemon 必须停掉**（`glcenc_daemon.py stop`）—— 它占着 NPU，
第二个进程再 Device.Open 会打架。脚本自己会检查并拒绝。

用法（板子上）：
    python3 /root/胶水拆解.py            # 3 轮
    python3 /root/胶水拆解.py 5          # 5 轮
"""
import hashlib
import os
import sys
import time

GLCDIR = '/root/glc'
SRC = os.environ.get('GLC_GLUE_SRC') or os.path.join(GLCDIR, 'glc_board_full.py')
TMP = os.environ.get('GLC_GLUE_TMP') or os.path.join(GLCDIR, 'glc_board_full_t.py')

HELPER = r'''
# ---------------- 插桩（自动插入，跑完就删文件）----------------
_PROF = {"t": None, "acc": {}}
def _T(name):
    now = time.perf_counter()
    if _PROF["t"] is not None:
        _PROF["acc"][name] = _PROF["acc"].get(name, 0.0) + (now - _PROF["t"])
    _PROF["t"] = now
def _T_start():
    _PROF["acc"] = {}
    _PROF["t"] = time.perf_counter()
def _T_dump(title):
    acc = _PROF["acc"]
    tot = sum(acc.values())
    print("\n---- %s ----" % title)
    for k, v in sorted(acc.items(), key=lambda kv: -kv[1]):
        print("   %-32s %7.1f ms  %5.1f%%" % (k, v * 1000.0, 100.0 * v / tot if tot else 0.0))
    print("   %-32s %7.1f ms" % ("各段合计", tot * 1000.0))
    _PROF["t"] = None
'''

# ---- (锚点原文, 追加内容)。每条锚点必须在源码里**恰好出现一次**，否则中止 ----
INSERTS = [
    ('    a = ap.parse_args()',
     '\n    _T_start()'),
    ('    os.makedirs(my_op, exist_ok=True)',
     '\n    _T("⓪ 开场 say + snapshot")'),
    ('    codebook, ysp_w, ysp_b = load_consts()',
     '\n    _T("① load_consts(已缓存)")'),
    ('    cb2, ysp_w64 = load_derived()',
     '\n    _T("①b load_derived(首次之后应为 0)")'),
    ('    (y, z), hard, wall = run_npu("s1", "%s/s1" % RUN)',
     '\n    _T("② S1 NPU")'),
    ('    z_idx = np.argmin(d, axis=1).astype(np.int32)',
     '\n    _T("③c z_vq argmin(1MB)")'),
    ('    z_hat_nhwc = codebook[z_idx].reshape(1, 4, 4, 256).astype(np.float32)',
     '\n    _T("④ codebook[z_idx] gather")'),
    ('    z_hat_nhwc.tofile("%s/s2/in0.ftmp" % RUN)',
     '\n    _T("⑤ 写 s2 输入 16KB")'),
    ('    (params,), hard, wall = run_npu("s2", "%s/s2" % RUN)',
     '\n    _T("⑥ S2 NPU")'),
    ('    q_dec = qs.astype(np.float32)',
     '\n    _T("⑦ separate_prior(split/max/倒数)")'),
    ('    common = common.reshape(1, 256, 16, 16)',
     '\n    _T("⑧d reshape")'),
    ('    y_hat_so_far = np.zeros((1, C, H, W), dtype=np.float32)',
     '\n    _T("⑨ make_masks + y_scaled")'),
    ('            (s_raw, m_raw), hard, wall = run_npu(key, "%s/%s" % (RUN, key))',
     '\n            _T("⑩ 相位1-3：写2个输入(512KB)+NPU")'),
    ('        y_hat_so_far = (y_hat_so_far + y_hat).astype(np.float32)',
     '\n        _T("⑪ 相位：means/residual/round(4相位合计)")'),
    ('        sym = np.round(yv - mn).astype(np.int32).reshape(-1)',
     '\n        _T("⑫ 相位：compact x3 + sym")'),
    ('        sm.reshape(-1).astype(np.float32).tofile("%s/p%d_scales.f32" % (my_op, k))',
     '\n        _T("⑬ 相位：4 次 tofile(共 3MB, tmpfs)")'),
    ('    z_idx.tofile("%s/z_indices.i32" % my_op)',
     '\n    _T("⑭ z_indices 落盘")'),
    ('    say("   chunk=0x%X  +0x84=0x%08X (期望 0x%08X)" % (rbase, v84, VER_EXPECT))',
     '\n    _T("⑮ Device.Open + malloc + RegWin")'),
    ('    streams, cyc_total = pl_encode(my_op, rbase, chunk, reg)',
     '\n    _T("⑯ pl_encode(glc2_pack 探针+定稿)")'),
    ('                            Z_INDEX_BITS)',
     '\n    _T("⑰ zpay = pack_fixed_width")'),
    ('    open(out_path, "wb").write(blob)',
     '\n    _T("⑱ 拼容器 + 写文件")'),
    ('           len(blob), 8.0 * len(blob) / 65536.0))',
     '\n    _T("⑲ 结果打印(含 bpp/say)")'),
]

# 插桩辅助函数挂在**模块级**（要能跨 main() 调用），放在 def main(): 前面
PREPEND = ('def main():', HELPER + '\n\ndef main():')

# ---- 按原求值顺序拆开的两处（产物必须不变）----
SPLIT = [
    ('''    d = (zz ** 2).sum(1, keepdims=True) + cb2[None, :] - 2.0 * (zz @ codebook.T)''',
     '''    d = (zz ** 2).sum(1, keepdims=True)
    _T("③a z_vq 距离项(zz**2)")
    d = d + cb2[None, :]
    _T("③a2 + cb2（已缓存；改前是 codebook**2.sum 26ms）")
    d = d - 2.0 * (zz @ codebook.T)
    _T("③b z_vq 矩阵乘 16x16384x256 = 67M MAC")'''),
    ('''    common = (ysp_w64 @ params.reshape(768, -1).astype(np.float64)
              + ysp_b.astype(np.float64)[:, None]).astype(np.float32)''',
     '''    _p64 = params.reshape(768, -1).astype(np.float64)
    _T("⑧b params -> f64")
    common = (ysp_w64 @ _p64 + ysp_b.astype(np.float64)[:, None]).astype(np.float32)
    _T("⑧c 1x1 卷积 f64 (50M MAC) + bias")'''),
]


def build():
    """★ 锚点一律按**整行**匹配（锚点+换行），否则锚点可能只是某行的前缀，
    插下去就把那行劈成两半（踩过：`... 65536.0)` 只是 `... 65536.0))` 的前缀）。"""
    src = open(SRC, 'rb').read()
    base_md5 = hashlib.md5(src).hexdigest()

    def one(old, new, tag):
        a = old.encode('utf-8') + b'\n'
        n = src.count(a)
        if n != 1:
            print('!! %s 锚点整行命中 %d 次（应为 1）：%r' % (tag, n, old.strip()[:60]))
            return False
        return True

    global _src
    _src = src

    def apply(old, new):
        global _src
        a = old.encode('utf-8') + b'\n'
        _src = _src.replace(a, new.encode('utf-8') + b'\n', 1)

    old, new = PREPEND
    if not one(old, new, '辅助函数'):
        return None, base_md5
    apply(old, new)
    for old, new in SPLIT:
        if not one(old, new, '拆分'):
            return None, base_md5
        apply(old, new)
    for anchor, add in INSERTS:
        if not one(anchor, add, '插桩'):
            return None, base_md5
        apply(anchor, anchor + add)
    src = _src
    open(TMP, 'wb').write(src)
    return TMP, base_md5


def daemon_alive():
    sock = '/var/run/glcenc.sock'
    if not os.path.exists(sock):
        return False
    import socket
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(3)
    try:
        s.connect(sock)
        s.sendall(b'PING\n')
        return s.recv(200).startswith(b'PONG')
    except Exception:
        return False
    finally:
        s.close()


def main():
    dry = '--dry' in sys.argv
    n_iter = 1 if dry else (int([x for x in sys.argv[1:] if x.isdigit()][0])
                            if any(x.isdigit() for x in sys.argv[1:]) else 3)

    tmp, base_md5 = build()
    if tmp is None:
        print('\n源码锚点对不上 —— 板上那份 glc_board_full.py 可能改过了，先看一眼再插桩。')
        return 2
    print('被拆解的源码：%s  md5=%s' % (SRC, base_md5))
    if dry:
        import py_compile
        py_compile.compile(tmp, doraise=True)
        print('--dry：插桩后的源码语法 OK（%d 字节），已删除' % os.path.getsize(tmp))
        os.remove(tmp)
        return 0

    if daemon_alive():
        print('\n!! 常驻编码器还活着（占着 NPU）。先 `python3 /root/glcenc_daemon.py stop` 再跑')
        os.remove(tmp)
        return 2

    sys.path.insert(0, GLCDIR)
    os.chdir(GLCDIR)
    try:
        import glc_board_full_t as G
        import glc_rsd as R
        import glc_rsd_cpu as RC
        print('补丁: %s' % ' / '.join(RC.patch(G)))
        t0 = time.time()
        eng = R.Engine(G.MODELS)
        print('引擎载入 %.1f s' % (time.time() - t0))
        G.run_npu = lambda k, c: eng.run(k, c)

        for i in range(n_iter):
            G._T_start()
            sys.argv = ['glc_board_full.py', '--sample', '0', '--out', '/tmp/glue%d.glc' % i]
            RC.STAT['rounds'] = 0
            RC.STAT['skip_final'] = 0
            t0 = time.perf_counter()
            rc = G.main()
            wall = (time.perf_counter() - t0) * 1000.0
            G._T_dump('第 %d 轮  rc=%s  main() 墙钟 %.0f ms  glc2_pack 探针 %d 轮%s'
                      % (i + 1, rc, wall, RC.STAT['rounds'],
                         '（复用探针产物）' if RC.STAT['skip_final'] else ''))
            print('   容器 md5 = %s' % hashlib.md5(open('/tmp/glue%d.glc' % i, 'rb').read()).hexdigest())
    finally:
        try:
            os.remove(TMP)
            print('\n已删除临时模块 %s' % TMP)
        except OSError:
            pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
