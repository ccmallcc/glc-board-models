#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gige_grab.py —— 网口相机连续取帧，写入 /dev/shm 供显示界面读取

配合 gige_shim.py（拦截 cv2.VideoCapture）使用，glc_ui.py 无需修改。

共享区约定（都在 tmpfs）：
    /dev/shm/gigecam.bin   裸 RGB 帧（w*h*3，HWC 行优先）
    /dev/shm/gigecam.meta  一行文本："<w> <h> <seq> <ts>"

原子性：先写 .bin.tmp 再 os.replace；meta 最后写。读方按 seq 校验。

用法：python3 gige_grab.py [--w 256] [--h 256]
"""
import ctypes
import os
import sys
import time
from ctypes import byref, memset, sizeof

os.environ.setdefault('MVCAM_SDK_PATH', '/opt/MVS')
os.environ.setdefault('MVCAM_COMMON_RUNENV', '/opt/MVS/lib')
os.environ.setdefault('LD_LIBRARY_PATH',
                      '/opt/MVS/lib/aarch64:' + os.environ.get('LD_LIBRARY_PATH', ''))
sys.path.insert(0, '/opt/MVS/Samples/aarch64/Python/MvImport')
from MvCameraControl_class import *      # noqa: E402,F401,F403

BIN = '/dev/shm/gigecam.bin'
META = '/dev/shm/gigecam.meta'
CTL = '/dev/shm/gigecam.ctl'          # UI -> 本进程：一行 "<节点> <值>"
CTLREP = '/dev/shm/gigecam.ctlrep'    # 本进程 -> UI："0" 成功，非 0 失败
STAT = '/dev/shm/gigecam.stat'        # 本进程 -> UI：当前曝光/增益，供 UI 显示
REQ = '/dev/shm/gigecam.req'          # UI -> 本进程：存在即请求"读回白平衡比值"
RATIOS = '/dev/shm/gigecam.ratios'    # 本进程 -> UI："Red=.. Green=.. Blue=.."


def _read_ratios(cam):
    """读回三个通道当前的 BalanceRatio。

    ★ 为什么要这个：`BalanceRatio` 是**每个 selector 一份**，读之前必须先切
      `BalanceRatioSelector`。相机自动白平衡收敛后会把这三个值改掉，UI 不知道
      ⇒ 手动 +/- 发绝对值时会**把自动白平衡的结果覆盖掉**，画面跳回偏绿。
      有了读回，手动档就能在自动结果的基础上做乘性微调。
    """
    out = {}
    for sel in ('Red', 'Green', 'Blue'):
        cam.MV_CC_SetEnumValueByString('BalanceRatioSelector', sel)
        it = MVCC_INTVALUE_EX()
        memset(byref(it), 0, sizeof(it))
        if cam.MV_CC_GetIntValueEx('BalanceRatio', it) == 0:
            out[sel] = it.nCurValue
        else:
            st = MVCC_FLOATVALUE()
            memset(byref(st), 0, sizeof(st))
            if cam.MV_CC_GetFloatValue('BalanceRatio', st) == 0:
                out[sel] = int(st.fCurValue)
    cam.MV_CC_SetEnumValueByString('BalanceRatioSelector', 'Green')
    try:
        with open(RATIOS + '.tmp', 'w') as f:
            f.write('Red=%d Green=%d Blue=%d\n'
                    % (out.get('Red', 0), out.get('Green', 0), out.get('Blue', 0)))
        os.replace(RATIOS + '.tmp', RATIOS)
    except OSError:
        pass
PIXEL_RGB8 = 0x02180014
SENS_W, SENS_H = 1280, 960


def _to_int(s):
    """把 "2048" 和 "2048.0" 都转成 int。

    ★ 2026-10-20 实测：BalanceRatio 是**整数节点**，而 UI 按浮点格式发（"2048.0"），
      内置 int("2048.0") 直接抛 ValueError ⇒ 整数分支被跳过 ⇒ 整条命令失败
      （ctlrep = -1），**白平衡完全没生效**，而界面上看起来"发出去了"。
    """
    return int(float(s))


def _ctl_apply(cam):
    """处理 UI 下发的节点写入。没有请求就立刻返回，绝不阻塞抓帧。

    ★ 2026-10-20 22:55 改成**按行遍历**：原来只读一行，于是"同一帧连发两条"
      时后一条会把前一条覆盖掉（实测踩过，症状是"改了曝光没反应"）。
      现在 ctl 文件可以有任意多行，按顺序逐条执行；白平衡要一次写
      Selector+Ratio 好几次，全靠这个。
    """
    try:
        with open(CTL) as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        os.unlink(CTL)
    except OSError:
        return
    if not lines:
        return
    rc = 0
    failname = ''
    for line in lines:
        parts = line.split(None, 1)
        if len(parts) != 2:
            rc = -1
            continue
        name, val = parts[0], parts[1]
        one = -1
        for fname, cast in (('MV_CC_SetFloatValue', float),
                            ('MV_CC_SetIntValue', _to_int),
                            ('MV_CC_SetEnumValueByString', str)):
            try:
                v = cast(val)
            except ValueError:
                continue
            try:
                if getattr(cam, fname)(name, v) == 0:
                    one = 0
                    break
            except Exception:
                pass
        if one != 0:
            rc = one
            if not failname:
                failname = name
    try:
        with open(CTLREP + '.tmp', 'w') as f:
            # 除了返回码，把**第一个失败的节点名**也写出来 —— 否则只会看到 -1，
            # 根本不知道是哪个节点被拒（白平衡那次就是这么卡住的）。
            f.write('%d %s\n' % (rc, failname))
        os.replace(CTLREP + '.tmp', CTLREP)
    except OSError:
        pass


FLOAT_NODES = ('ExposureTime', 'Gain', 'Gamma',
               'AcquisitionFrameRate', 'ResultingFrameRate')
INT_NODES = ('GevSCPD', 'DeviceLinkThroughputLimit', 'AcquisitionBurstFrameCount')


def _pub_stat(cam):
    """把关键节点写成一个单行文件，UI/诊断直接读文件，不做任何 IPC 阻塞。

    ★ 为什么把帧率节点也塞进来：2026-10-20 实测曝光扫描发现
      1~2 ms 时 10.0 fps、4~40 ms 时全都 6.4 fps —— 说明卡住帧率的**不是曝光**，
      得看相机自己的 AcquisitionFrameRate / ResultingFrameRate / GevSCPD。
      但相机被本进程独占（Exclusive），别的进程开不了，所以只能由本进程读出来。
    """
    vals = []
    for node in FLOAT_NODES:
        st = MVCC_FLOATVALUE()
        memset(byref(st), 0, sizeof(st))
        if cam.MV_CC_GetFloatValue(node, st) == 0:
            vals.append('%s=%.3f' % (node, st.fCurValue))
    for node in INT_NODES:
        it = MVCC_INTVALUE_EX()
        memset(byref(it), 0, sizeof(it))
        if cam.MV_CC_GetIntValueEx(node, it) == 0:
            vals.append('%s=%d' % (node, it.nCurValue))
    try:
        with open(STAT + '.tmp', 'w') as f:
            f.write(' '.join(vals) + '\n')
        os.replace(STAT + '.tmp', STAT)
    except OSError:
        pass


def main():
    w = int(sys.argv[sys.argv.index('--w') + 1]) if '--w' in sys.argv else 256
    h = int(sys.argv[sys.argv.index('--h') + 1]) if '--h' in sys.argv else 256

    MvCamera.MV_CC_Initialize()
    dl = MV_CC_DEVICE_INFO_LIST()
    MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE, dl)
    if dl.nDeviceNum == 0:
        print('没找到相机', flush=True); return 1
    cam = MvCamera()
    cam.MV_CC_CreateHandle(dl.pDeviceInfo[0].contents)
    opened = False
    for _ in range(10):
        if cam.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0) == 0:
            opened = True; break
        time.sleep(1.0)
    if not opened:
        print('打不开相机（被占用？）', flush=True); return 2

    # ★★★ 2026-10-20 实测根因：GigE 包大小必须 ≤ 网卡 MTU！
    #   相机出厂/上次 PC 会话留下的 GevSCPSPacketSize = 8164，而板子 eth0 MTU = 1500
    #   ⇒ 每帧被分片丢弃，收到的数据是碎片拼的"马赛克噪声"（neighbor 差 52.69）。
    #   设成 1444（< 1472）后 neighbor 降到 6.52，画面正常。
    #   注意该节点 nInc = 8（不是 4），1444 实测可写；1472 反而被拒。
    r = cam.MV_CC_SetIntValue('GevSCPSPacketSize', 1444)
    print('set GevSCPSPacketSize=1444 ret=%#x' % (r & 0xFFFFFFFF), flush=True)
    if r != 0:
        print('!! 包大小设置失败，画面可能仍是碎片（检查 MTU）', flush=True)

    cam.MV_CC_SetIntValue('OffsetX', 0)
    cam.MV_CC_SetIntValue('OffsetY', 0)
    cam.MV_CC_SetIntValue('Width', w)
    cam.MV_CC_SetIntValue('Height', h)
    if (w, h) != (SENS_W, SENS_H):
        cam.MV_CC_SetIntValue('OffsetX', (SENS_W - w) // 2)
        cam.MV_CC_SetIntValue('OffsetY', (SENS_H - h) // 2)
    cam.MV_CC_SetEnumValue('PixelFormat', PIXEL_RGB8)

    # ★ 启动时把帧率/曝光/增益固定下来（2026-10-20 实测结论）
    #   ① AcquisitionFrameRate 是**显式限速**，出厂/上次会话留下的 10.000 就是
    #      原来只有 10 fps 的真因（不是曝光、不是链路：GevSCPD=0，65 fps 才占 102 Mbps）。
    #   ② 顺序必须是「先关自动 → 设帧率 → 再设曝光」。
    #      但注意：这条顺序**不是相机强制的**。早先我以为"相机把曝光上限绑在帧周期上、
    #      超了静默拒绝"，**那是错的**（2026-10-20 22:40 实测更正）：相机会接受
    #      500 ms / 1000 ms，只是把 ResultingFrameRate 降到 2.0 / 1.0。
    #      当时看起来"被拒"的真因是：连发了两条 ctl，而本进程每轮循环只消费一条，
    #      前一条被后一条覆盖了。保持这个顺序只是让启动配置更可预测。
    #   ③ 用户 2026-10-20 选定 20 fps。曝光取 40 ms（留出 20% 余量到 50 ms 周期），
    #      增益 20 dB —— 这个组合实测帧均值 ≈ 100、高光裁剪 0%。
    #    ④ 2026-10-20 用户定：**帧率下限 15 fps**（先前是 10，后来收紧）。
    #      工作点就取下限 15 fps（周期 66.7 ms），曝光留 20% 余量取 30 ms 起，
    #      由 UI 的自动曝光在 exp_cap() 允许范围内往 60 ms 推。
    FPS, EXP_US, GAIN_DB = 15.0, 50000.0, 14.0   # 曝光 50 ms（用户 2026-10-22 定，原 60）；增益只作基线
    cam.MV_CC_SetEnumValueByString('ExposureAuto', 'Off')
    cam.MV_CC_SetEnumValueByString('GainAuto', 'Off')
    r1 = cam.MV_CC_SetFloatValue('AcquisitionFrameRate', FPS)
    r2 = cam.MV_CC_SetFloatValue('ExposureTime', EXP_US)
    r3 = cam.MV_CC_SetFloatValue('Gain', GAIN_DB)
    print('set fps=%.0f ret=%#x | exp=%.0f ret=%#x | gain=%.1f ret=%#x'
          % (FPS, r1 & 0xFFFFFFFF, EXP_US, r2 & 0xFFFFFFFF, GAIN_DB, r3 & 0xFFFFFFFF),
          flush=True)
    if r2 != 0:
        print('!! 曝光设置失败（帧率是否太高？曝光上限绑定帧周期）', flush=True)

    # ★ Q9-#4：设参可能失败（相机默认是全尺寸 UserSet）。必须回读确认，
    #   否则会把 1280x960 写进按 256x256 约定的共享区，显示端全错且无报警。
    def _readi(node):
        st = MVCC_INTVALUE_EX(); memset(byref(st), 0, sizeof(st))
        return st.nCurValue if cam.MV_CC_GetIntValueEx(node, st) == 0 else None

    gw, gh = _readi('Width'), _readi('Height')
    print('回读 Width=%s Height=%s（请求 %dx%d）' % (gw, gh, w, h), flush=True)
    if (gw, gh) != (w, h):
        print('!! 尺寸设置失败，拒绝写入共享区（否则显示端会错）', flush=True)
        cam.MV_CC_CloseDevice(); cam.MV_CC_DestroyHandle()
        return 3

    cam.MV_CC_StartGrabbing()
    print('抓帧中 %dx%d -> %s' % (w, h, BIN), flush=True)

    seq = 0
    frame = MV_FRAME_OUT()
    try:
        _pub_stat(cam)
        while True:
            _ctl_apply(cam)
            if os.path.exists(REQ):
                try:
                    os.unlink(REQ)
                except OSError:
                    pass
                _read_ratios(cam)
            memset(byref(frame), 0, sizeof(frame))
            r = cam.MV_CC_GetImageBuffer(frame, 2000)
            if r != 0:
                time.sleep(0.05); continue
            fi = frame.stFrameInfo
            data = ctypes.string_at(frame.pBufAddr, fi.nFrameLen)
            cam.MV_CC_FreeImageBuffer(frame)
            # ★ Q9-#4：再按"实际帧"校验一次，尺寸不符绝不写入共享区
            if fi.nWidth != w or fi.nHeight != h or len(data) != w * h * 3:
                print('!! 帧尺寸异常 %dx%d len=%d（期望 %dx%d）——跳过'
                      % (fi.nWidth, fi.nHeight, len(data), w, h), flush=True)
                continue
            tmp = BIN + '.tmp'
            with open(tmp, 'wb') as f:
                f.write(data)
            os.replace(tmp, BIN)
            seq += 1
            with open(META + '.tmp', 'w') as f:
                f.write('%d %d %d %.3f\n' % (fi.nWidth, fi.nHeight, seq, time.time()))
            os.replace(META + '.tmp', META)
            if seq % 10 == 0:
                _pub_stat(cam)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            cam.MV_CC_StopGrabbing(); cam.MV_CC_CloseDevice(); cam.MV_CC_DestroyHandle()
            MvCamera.MV_CC_Finalize()
        except Exception:
            pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
