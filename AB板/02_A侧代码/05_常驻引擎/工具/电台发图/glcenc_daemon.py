# ==============================================================================
# 版本横幅（2026-10-18 加）：本文件被**就地改过**，板上可能还是旧版。
#   当前标签    : v20261018-512param
#   板上那版 md5 : 4f51fd3d …   ← 回滚用它；历史副本见下
#                工具/_历史_板端文件/glcenc_daemon.4f51fd3d.py
#   板上那版来源: git 65e1d86:工具/电台发图/glcenc_daemon.py
#   改了什么    : 漂移分两步：先 raw256（9b23ec5, 670becce）→ 再 512 参数化（7c4d0d7）
#   回滚步骤/对照表: 工具/版本对照_板端文件.md
#   ⚠️ 本文件不写自己的 md5（自指会变），现版 md5 只在对照表里。
# ==============================================================================
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""glcenc_daemon.py —— 常驻 GLC 编码器（A 板），v3

v3 相比 v2 多了什么
------------------
把**预处理**（缩放 + 居中裁 256×256 + 归一化到 [-1,1]）也搬进来了。
之前每张图都要起一个 `enc_image.py` 进程（Python + PIL 启动 ~1 s），
现在守护进程里 PIL/numpy 早就 import 好了，这段几乎免费。

⇒ 单张端到端从 ~2.5 s 降到 **~1.2 s**（编码本身 1.05 s）。
   预处理逻辑是**照抄** `/root/enc_image.py` 的 `build()`，保证逐字节一致。

为什么要有它（速度）
------------------
单张链 `glc_board_full.py` 每张图都要重新 Open 一次 NPU、重新载入 5 个子图：
    NPU s1  wall 6.6 s / hard 0.35 s      <- 99% 是载入
    NPU s2  wall 0.6 s / hard 0.003 s
    NPU s3  wall 0.54 s × 3 / hard 0.002 s
⇒ 一次编码 10~17 s，真正算的只有 **355 ms**。
常驻引擎把 5 个子图只载入一次，之后每张只 forward。
**实测**：之后每张 **1.03~1.11 s**，容器与单张链**逐字节一致**。

协议（逐行文本，unix socket /var/run/glcenc.sock）
--------------------------------------------------
    PING                                   -> PONG <pid> <uptime_s> <n_enc> <last_err>
    ENC    <name> <in.ftmp>   <out.glc>    -> OK <bytes> <md5> <enc_s> <prep_s>
    ENCIMG <name> <image.jpg> <out.glc> [mode] -> OK <bytes> <md5> <enc_s> <prep_s>
    ENCBATCH <outdir> <name=img> [name=img ...] -> 每张一行 OK/ERR，最后一行 DONE <n_ok>/<n>
    STOP                                   -> BYE

用法
----
    python3 /root/glcenc_daemon.py start     # 后台起（立刻返回，引擎后台载入约 8 s）
    python3 /root/glcenc_daemon.py status
    python3 /root/glcenc_daemon.py stop
    python3 /root/glcenc_client.py PING
    python3 /root/glcenc_client.py ENCIMG p1 /root/photo/p1.jpg /root/enc_out/p1.glc

安全设计
--------
* **空闲自动退出**（默认 300 s，`GLC_ENC_IDLE` 可调，0=不退），不长期占着 NPU。
* socket 权限 0666，但只在 root 的机器上跑。
* 出错的张**绝不冒名顶替**：只有 `rc==0` 才写输出，失败一律 `ERR`。
"""
import hashlib
import io
import os
import shutil
import socket
import sys
import time
import traceback

os.environ.setdefault('GLC_RSD_RESET', 'each')   # ★ 批量正确性必需

SOCK = os.environ.get('GLC_ENC_SOCK', '/var/run/glcenc.sock')
# ★ 2026-10-17：启动锁。载 5 个子图要 9~18 s，这期间 socket 还不存在，
#   若此时又来一个 start 会起第二个 daemon（两个引擎抢 NPU ⇒ Write failed）。
STARTLOCK = os.environ.get('GLC_ENC_STARTLOCK', '/var/run/glcenc_start.pid')


def _pid_alive(p):
    try:
        os.kill(int(p), 0)
        return True
    except Exception:
        return False

LOG_PATH = os.environ.get('GLC_ENC_LOG', '/root/glcenc_daemon.log')
IDLE = float(os.environ.get('GLC_ENC_IDLE', '300'))
GLCDIR = '/root/glc'
IN0 = GLCDIR + '/run/s1/in0.ftmp'
PLGLC = GLCDIR + '/pack/full_img0.glc'

_G = _rsd = _rsd_cpu = None
_engine = None
_n_enc = 0
_t_start = None
_t_last = None
_last_err = '-'


def log(*a):
    msg = time.strftime('%F %T ') + ' '.join(str(x) for x in a)
    try:
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(msg + '\n')
    except Exception:
        pass


# ------------------------------------------------------------------ 预处理
def prepare(image_path, mode='fit'):
    """照抄 /root/enc_image.py 的 build()，保证与它逐字节一致。

    返回 (numpy (1,256,256,3) float32 in [-1,1], 预览图 or None)
    """
    import numpy as np

    # 目标边长：出厂 256；512 只有显式放行才用（与 glc_board_full.py 同一套开关）
    _SZ = int(os.environ.get('GLC_SIZE', '256'))
    if _SZ not in (256, 512):
        raise RuntimeError('GLC_SIZE 只能是 256 或 512（收到 %r）' % _SZ)
    if _SZ != 256 and os.environ.get('GLC_ALLOW_512', '0') != '1':
        raise RuntimeError('GLC_SIZE=512 从未上板验证过（模型/容器/B 端都要换）；确实要试请设 GLC_ALLOW_512=1')

    # ★ 2026-10-18 新增 mode='raw256'：**零解码、零重采样**入口。
    #   读一个"恰好 256*256*3 字节"的裸 RGB8 文件（HWC 行优先），直接归一化。
    #   用途：工业相机（如 MV-CE013-50GC）用 ROI 直接出 256x256，或任何"已在外面裁好"的来源
    #   ⇒ 预处理只剩归一化(~5 ms)，对比 fit 模式的 289 ms（解码 90 + LANCZOS 190）。
    #   **不经过 PIL**，所以没有解码、没有重采样。逐字节等价性由
    #   `工具/回归/单元测试_raw256入口.py` 保证（与 crop 模式比）。
    if mode in ('raw256', 'raw'):
        n = _SZ * _SZ * 3
        raw = np.fromfile(image_path, dtype=np.uint8)
        if raw.size != n:
            raise RuntimeError('%s: 文件 %d 字节，要 %d 字节（%d*%d*3，RGB8 行优先）'
                               % (mode, raw.size, n, _SZ, _SZ))
        a = raw.reshape(_SZ, _SZ, 3).astype(np.float32)
        t = a / np.float32(127.5) - np.float32(1.0)
        t = t.reshape(1, _SZ, _SZ, 3).astype(np.float32)
        return t, None

    from PIL import Image          # ★ 故意放在 raw256 分支之后：那条路连 PIL 都不 import
    im = Image.open(image_path).convert('RGB')
    w, h = im.size
    if mode == 'crop':
        if min(w, h) < _SZ:
            raise RuntimeError('图太小(%dx%d)：crop 模式需要至少 %dx%d' % (w, h, _SZ, _SZ))
        left = (w - _SZ) // 2
        top = (h - _SZ) // 2
        im = im.crop((left, top, left + _SZ, top + _SZ))
    elif mode == 'squash':
        im = im.resize((_SZ, _SZ), Image.LANCZOS)
    else:  # fit：按短边缩放到 _SZ，再中心裁
        s = float(_SZ) / min(w, h)
        nw = max(_SZ, int(round(w * s)))
        nh = max(_SZ, int(round(h * s)))
        im = im.resize((nw, nh), Image.LANCZOS)
        left = (nw - _SZ) // 2
        top = (nh - _SZ) // 2
        im = im.crop((left, top, left + _SZ, top + _SZ))

    a = np.asarray(im, dtype=np.float32)            # HWC RGB 0..255
    t = a / np.float32(127.5) - np.float32(1.0)     # -> [-1,1]
    t = t.reshape(1, _SZ, _SZ, 3).astype(np.float32)
    return t, im


# ------------------------------------------------------------------ 引擎
def ensure_engine():
    global _engine
    if _engine is None:
        t = time.time()
        log('[引擎] 载入 5 个子图 …')
        _engine = _rsd.Engine(_G.MODELS)
        log('[引擎] 就绪 %.3f s' % (time.time() - t))
    return _engine


def _run_npu(key, cwd):
    return ensure_engine().run(key, cwd)


def boot_engine():
    global _G, _rsd, _rsd_cpu
    os.chdir(GLCDIR)
    sys.path.insert(0, GLCDIR)
    t = time.time()
    import glc_board_full as G
    import glc_rsd as R
    import glc_rsd_cpu as RC
    _G, _rsd, _rsd_cpu = G, R, RC

    applied = _rsd_cpu.patch(_G)
    log('[补丁] ' + ' / '.join(applied))
    _G.run_npu = _run_npu                 # ★ 必须在建引擎之前挂上
    ensure_engine()                       # 立刻真载入，让第一次请求就快
    log('[boot] 完成 %.3f s' % (time.time() - t))


# ------------------------------------------------------------------ 单张
def _encode_from_ftmp(outpath):
    """跑一次 glc_board_full，成功返回 (bytes, md5, enc_secs)。"""
    t0 = time.time()
    sys.argv = ['glc_board_full.py', '--sample', '0']
    cap = io.StringIO()
    old = sys.stdout
    rc = None
    # ★ 2026-10-17：`GLC_ENC_PROFILE=1` 时对一次编码做 cProfile（默认关闭、零开销）。
    #   目的：把 0.876 s 里"胶水"那 ~139 ms 拆到函数级。
    #   ⚠️ profiling 本身有开销，**只看相对分布，不要拿绝对毫秒当实测**。
    _prof = None
    if os.environ.get('GLC_ENC_PROFILE'):
        try:
            import cProfile
            _prof = cProfile.Profile()
            _prof.enable()
        except Exception:
            _prof = None
    try:
        sys.stdout = cap
        rc = _G.main()
    except SystemExit as e:
        rc = e.code
    except Exception as e:
        traceback.print_exc(file=cap)
        rc = 'EXC:%s' % e
    finally:
        sys.stdout = old
        if _prof is not None:
            try:
                import pstats
                _prof.disable()
                with open('/root/glcenc_profile.txt', 'w', encoding='utf-8') as _pf:
                    pstats.Stats(_prof, stream=_pf).sort_stats('cumulative').print_stats(40)
            except Exception:
                pass
    dt = time.time() - t0

    # ★ 2026-10-17：`_G.main()` 的 stdout 原来只在**失败时**才被用（见下面 rc!=0 的报错），
    #   而它里面就有 glc_board_full 的分阶段耗时 —— 成功时全丢。
    #   加一个环境变量开关（默认关闭、零开销）把它落盘，用于回答"这 0.876 s 花在哪"。
    #   用法：GLC_ENC_DEBUG=1 起 daemon，然后发一张，看 /root/glcenc_last_stdout.log
    if os.environ.get('GLC_ENC_DEBUG'):
        try:
            with open('/root/glcenc_last_stdout.log', 'a', encoding='utf-8') as _f:
                _f.write('=== enc %.3f s ===\n%s\n' % (dt, cap.getvalue()))
        except Exception:
            pass

    # ★ 只有 rc==0 才认结果（否则会把上一张的残留容器报成本张的）
    if rc != 0:
        raise RuntimeError('编码 rc=%s (%.3f s) %s' % (rc, dt, cap.getvalue()[-200:].replace('\n', ' ')))
    if not os.path.exists(PLGLC):
        raise RuntimeError('没产出容器')

    d = os.path.dirname(outpath)
    if d:
        os.makedirs(d, exist_ok=True)
    shutil.copyfile(PLGLC, outpath)
    blob = open(outpath, 'rb').read()
    return len(blob), hashlib.md5(blob).hexdigest(), dt


def do_enc(name, inpath, outpath):
    """从现成的 ftmp 编码。"""
    global _n_enc
    if not os.path.exists(inpath):
        raise RuntimeError('输入不存在: %s' % inpath)
    shutil.copyfile(inpath, IN0)
    nb, md5, dt = _encode_from_ftmp(outpath)
    _n_enc += 1
    return nb, md5, dt, 0.0


def do_encimg(name, image_path, outpath, mode='fit', preview=''):
    """从图片直接编码（预处理在进程内做，省掉一个 enc_image.py 进程）。"""
    global _n_enc
    if not os.path.exists(image_path):
        raise RuntimeError('图片不存在: %s' % image_path)
    t0 = time.time()
    t, im = prepare(image_path, mode)
    t.tofile(IN0)
    prep = time.time() - t0
    if preview:
        try:
            d = os.path.dirname(preview)
            if d:
                os.makedirs(d, exist_ok=True)
            im.save(preview)
        except Exception as e:
            log('[预览失败] %s' % e)
    nb, md5, dt = _encode_from_ftmp(outpath)
    _n_enc += 1
    return nb, md5, dt, prep


# ------------------------------------------------------------------ 服务
def cleanup_sock():
    try:
        os.unlink(SOCK)
    except OSError:
        pass


def _handle(req):
    """返回一行（或 ENCBATCH 时多行）文本。"""
    global _last_err
    p = req.split()
    cmd = p[0].upper()

    if cmd == 'PING':
        return ['PONG %d %.1f %d %s' % (os.getpid(), time.time() - _t_start, _n_enc, _last_err)]

    if cmd == 'ENC' and len(p) >= 4:
        nb, md5, dt, prep = do_enc(p[1], p[2], p[3])
        log('[ENC]    %-16s %5d B  %s  enc %.3f s' % (p[1], nb, md5, dt))
        return ['OK %d %s %.3f %.3f' % (nb, md5, dt, prep)]

    if cmd == 'ENCIMG' and len(p) >= 4:
        mode = p[4] if len(p) >= 5 else 'fit'
        nb, md5, dt, prep = do_encimg(p[1], p[2], p[3], mode)
        log('[ENCIMG] %-16s %5d B  %s  enc %.3f s / prep %.3f s'
            % (p[1], nb, md5, dt, prep))
        return ['OK %d %s %.3f %.3f' % (nb, md5, dt, prep)]

    if cmd == 'ENCBATCH' and len(p) >= 3:
        outdir = p[1]
        os.makedirs(outdir, exist_ok=True)
        lines = []
        n_ok = 0
        for item in p[2:]:
            if '=' not in item:
                lines.append('ERR %s 格式应为 name=image' % item)
                continue
            nm, ip = item.split('=', 1)
            try:
                nb, md5, dt, prep = do_encimg(nm, ip, os.path.join(outdir, nm + '.glc'))
                n_ok += 1
                lines.append('OK %s %d %s %.3f %.3f' % (nm, nb, md5, dt, prep))
                log('[BATCH]  %-16s %5d B  %s  enc %.3f s / prep %.3f s'
                    % (nm, nb, md5, dt, prep))
            except Exception as e:
                lines.append('ERR %s %s' % (nm, str(e).replace('\n', ' ')[:160]))
                log('[BATCH失败] %s -> %s' % (nm, e))
        lines.append('DONE %d/%d' % (n_ok, len(p) - 2))
        return lines

    return ['ERR 未知命令或参数不足: %s' % cmd]


def serve():
    global _t_start, _t_last, _last_err
    cleanup_sock()
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK)
    os.chmod(SOCK, 0o666)
    srv.listen(4)
    srv.settimeout(1.0)
    _t_start = _t_last = time.time()
    log('[服务] 监听 %s (pid %d, 空闲 %.0f s 自退)' % (SOCK, os.getpid(), IDLE))

    while True:
        try:
            conn, _ = srv.accept()
        except socket.timeout:
            if IDLE and (time.time() - _t_last) > IDLE:
                log('[服务] 空闲 %.0f s，自动退出（把 NPU 让出来）' % IDLE)
                srv.close()
                cleanup_sock()
                return 0
            continue
        except OSError:
            cleanup_sock()
            return 0

        _t_last = time.time()
        try:
            f = conn.makefile('rwb')
            while True:
                line = f.readline()
                if not line:
                    break
                _t_last = time.time()
                req = line.decode('utf-8', 'replace').strip()
                if not req:
                    continue
                if req.split()[0].upper() == 'STOP':
                    f.write(b'BYE\n')
                    f.flush()
                    conn.close()
                    srv.close()
                    cleanup_sock()
                    log('[服务] STOP，退出')
                    return 0
                try:
                    reps = _handle(req)
                    _last_err = '-'
                except Exception as e:
                    _last_err = str(e).replace('\n', ' ')[:80]
                    reps = ['ERR %s' % _last_err]
                f.write(('\n'.join(reps) + '\n').encode())
                f.flush()
        except Exception:
            log('[连接异常]\n' + traceback.format_exc())
        finally:
            try:
                conn.close()
            except Exception:
                pass


# ------------------------------------------------------------------ 控制
def ping():
    if not os.path.exists(SOCK):
        return None
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(SOCK)
        s.sendall(b'PING\n')
        r = s.recv(300).decode(errors='replace').strip()
        s.close()
        return r
    except Exception:
        return None


def daemonize():
    if os.fork() > 0:
        sys.exit(0)
    os.setsid()
    if os.fork() > 0:
        sys.exit(0)
    # ★ 必须真的重定向 fd 0/1/2。
    #   只改 sys.stdout 没用：底层 fd 1 还连着 ssh 的管道，ssh 会一直等管道 EOF，
    #   于是 `python3 glcenc_daemon.py start` 永远不返回
    #   （实测踩过：ssh 客户端一路挂到 10 分钟超时）。
    fd = os.open('/dev/null', os.O_RDWR)
    os.dup2(fd, 0)
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    if fd > 2:
        os.close(fd)
    sys.stdin = open('/dev/null')
    sys.stdout = open(LOG_PATH, 'a', buffering=1)
    sys.stderr = sys.stdout


def main():
    act = sys.argv[1] if len(sys.argv) > 1 else 'start'

    if act == 'status':
        r = ping()
        if r:
            print('运行中: %s' % r)
            sys.exit(0)
        print('未运行（socket %s 不存在或连不上）' % SOCK)
        sys.exit(1)

    if act == 'stop':
        try:
            os.remove(STARTLOCK)
        except OSError:
            pass
        if not os.path.exists(SOCK):
            print('本来就没跑')
            sys.exit(0)
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(10)
            s.connect(SOCK)
            s.sendall(b'STOP\n')
            print(s.recv(200).decode(errors='replace').strip())
            s.close()
        except Exception as e:
            print('停止失败: %s' % e)
            sys.exit(1)
        sys.exit(0)

    if act == 'clean':
        # 强制清理（进程可能已经僵死）：删 socket + 杀掉残留进程
        cleanup_sock()
        print('已删 %s' % SOCK)
        sys.exit(0)

    if act != 'start':
        print(__doc__)
        sys.exit(2)

    if ping():
        print('已经在跑了，不重复启动')
        sys.exit(0)
    # ★ 正在启动中？（socket 还没建好，但引擎在载）⇒ 别起第二个
    if act == 'start' and os.path.exists(STARTLOCK):
        try:
            p = int(open(STARTLOCK).read().strip())
        except Exception:
            p = 0
        if p and _pid_alive(p):
            print('正在启动中(pid=%d，正在载入 5 个子图)，不重复启动；等它就绪即可' % p)
            sys.exit(0)
    # socket 在但 PING 不通 => 上次没退干净，清掉再起
    if os.path.exists(SOCK):
        log('[启动] socket 残留且无响应，清理后重启')
        cleanup_sock()

    daemonize()
    try:
        with open(STARTLOCK, 'w') as _lf:
            _lf.write(str(os.getpid()))
    except Exception:
        pass
    log('=' * 64)
    log('[启动] pid=%d  GLC_RSD_RESET=%s' % (os.getpid(), os.environ.get('GLC_RSD_RESET')))
    try:
        boot_engine()
    except Exception:
        log('[致命] 引擎启动失败\n' + traceback.format_exc())
        cleanup_sock()
        sys.exit(1)
    try:
        os.remove(STARTLOCK)
    except OSError:
        pass
    sys.exit(serve())


if __name__ == '__main__':
    main()
