#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mvs_enum_nodes.py -- 在板子上枚举 MV-CE013-50GC 真正存在的 GenICam 节点

为什么要有这个脚本：UI 里现在写着「曝光 = 数字(软件)」，那是给**旧的 USB UVC 相机**
写的（v4l2-ctl 里根本没有 exposure_* 控制项，gain/brightness 调了只动 0.3%）。
换成 GigE 相机 + MVS SDK 之后，硬件曝光/增益/白平衡**是真能调的**。
到底有哪些能调、范围多大，必须挨个探，不能靠猜。

用法（板上，root）：
    export MVCAM_SDK_PATH=/opt/MVS
    export MVCAM_COMMON_RUNENV=/opt/MVS/lib
    python3 mvs_enum_nodes.py                      # 只读枚举
    python3 mvs_enum_nodes.py --set ExposureTime=8000
    python3 mvs_enum_nodes.py --set BalanceWhiteAuto=Continuous
    python3 mvs_enum_nodes.py --set Gain=2.5

判读规则：
  [int]   0x00000000 + min/max/inc   -> 真的存在，能读写
  [float] 0x00000000 + min/max       -> 真的存在
  [enum]  0x00000000 + 可选值表       -> 真的存在
  [--]    非 0 错误码                -> 不存在 / 当前不可用（不是故障）
"""
import argparse
import os
import sys

os.environ.setdefault('MVCAM_SDK_PATH', '/opt/MVS')
os.environ.setdefault('MVCAM_COMMON_RUNENV', '/opt/MVS/lib')
for _p in ('/opt/MVS/lib', '/opt/MVS/lib/64', '/opt/MVS/lib/aarch64'):
    if os.path.isdir(_p):
        os.environ['LD_LIBRARY_PATH'] = _p + ':' + os.environ.get('LD_LIBRARY_PATH', '')
sys.path.insert(0, '/opt/MVS/Samples/aarch64/Python/MvImport')

from MvCameraControl_class import *  # noqa: E402,F401,F403

# ---- 候选节点：按"对图像控制的重要性"分组。存在与否由相机回答，不预设 ----
GROUPS = [
    ('曝光（高光的第一道闸）', [
        'ExposureMode', 'ExposureAuto', 'ExposureTime',
        'AutoExposureTimeLowerLimit', 'AutoExposureTimeUpperLimit',
        'ExposureTimeUpperLimit', 'AutoExposureControlPriority',
    ]),
    ('增益（第二道闸，影响噪声）', [
        'GainSelector', 'Gain', 'GainAuto',
        'AutoGainLowerLimit', 'AutoGainUpperLimit',
    ]),
    ('高光 / 色调曲线', [
        'GammaSelector', 'GammaEnable', 'Gamma',
        'BlackLevelEnable', 'BlackLevel',
        'DigitalShift', 'DigitalShiftEnable',
        'LUTEnable', 'LUTSelector',
        'HDR', 'MultiExposure',
    ]),
    ('白平衡', [
        'BalanceWhiteAuto', 'BalanceRatioSelector', 'BalanceRatio',
        'AutoWBLowerLimit', 'AutoWBUpperLimit',
    ]),
    ('色彩 / 锐度', [
        'Brightness', 'Contrast', 'Saturation', 'Hue',
        'Sharpness', 'SharpnessEnable',
        'ColorTransformationEnable', 'ColorTransformationMatrix',
    ]),
    ('像素 / 几何（直接决定压缩率）', [
        'PixelFormat', 'Width', 'Height', 'OffsetX', 'OffsetY',
        'WidthMax', 'HeightMax', 'PayloadSize', 'ADCBitDepth',
    ]),
    ('时基与链路', [
        'AcquisitionFrameRate', 'AcquisitionFrameRateEnable',
        'ResultingFrameRate', 'AcquisitionLineRate', 'AcquisitionBurstFrameCount',
        'TriggerMode', 'TriggerSource', 'TriggerActivation', 'TriggerDelay',
        'DeviceLinkThroughputLimit',
        'GevSCPSPacketSize', 'GevSCPD', 'GevHeartbeatTimeout',
    ]),
]


def probe(cam, name):
    """返回 (kind, text)。kind in {'int','float','enum','--'}"""
    st = MVCC_INTVALUE_EX()
    memset(byref(st), 0, sizeof(st))
    if cam.MV_CC_GetIntValueEx(name, st) == 0:
        return 'int', '%-10d  min=%-12d max=%-12d inc=%d' % (
            st.nCurValue, st.nMin, st.nMax, st.nInc)
    stf = MVCC_FLOATVALUE()
    memset(byref(stf), 0, sizeof(stf))
    if cam.MV_CC_GetFloatValue(name, stf) == 0:
        return 'float', '%-10.4f  min=%-12.4f max=%-12.4f' % (
            stf.fCurValue, stf.fMin, stf.fMax)
    ste = MVCC_ENUMVALUE()
    memset(byref(ste), 0, sizeof(ste))
    if cam.MV_CC_GetEnumValue(name, ste) == 0:
        names = []
        for i in range(min(ste.nSupportedNum, 8)):
            ent = MVCC_ENUMENTRY()
            memset(byref(ent), 0, sizeof(ent))
            ent.nValue = ste.nSupportValue[i]
            if cam.MV_CC_GetEnumEntrySymbolic(name, ent) == 0:
                names.append('%s=%d' % (ent.chSymbolicName.decode('ascii', 'replace'),
                                        ent.nValue))
            else:
                names.append('=%d' % ent.nValue)
        return 'enum', 'cur=%-4d  [%s]' % (ste.nCurValue, ' '.join(names))
    return '--', ''


def set_one(cam, name, val):
    for cast, setter in ((int, cam.MV_CC_SetIntValueEx),
                         (float, cam.MV_CC_SetFloatValue),
                         (str, cam.MV_CC_SetEnumValueByString)):
        try:
            v = cast(val) if cast is not str else val
        except ValueError:
            continue
        r = setter(name, v)
        if r == 0:
            print('[SET] %s = %s  -> OK' % (name, val))
            return 0
    print('[SET] %s = %s  -> 失败（三种类型都不接受）' % (name, val))
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--set', action='append', default=[], metavar='NAME=VALUE')
    args = ap.parse_args()

    MvCamera.MV_CC_Initialize()
    dl = MV_CC_DEVICE_INFO_LIST()
    MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE, dl)
    if dl.nDeviceNum == 0:
        print('没枚举到相机')
        return 1
    cam = MvCamera()
    cam.MV_CC_CreateHandle(dl.pDeviceInfo[0].contents)
    ok = False
    for mode, nm in ((MV_ACCESS_Monitor, 'Monitor'), (MV_ACCESS_Exclusive, 'Exclusive')):
        if cam.MV_CC_OpenDevice(mode, 0) == 0:
            print('已打开（%s 模式）\n' % nm)
            ok = True
            break
    if not ok:
        print('打开失败')
        return 2

    try:
        for name, val in (a.split('=', 1) for a in args.set):
            set_one(cam, name, val)
        if args.set:
            print()

        for title, names in GROUPS:
            print('=' * 72)
            print(title)
            print('=' * 72)
            for n in names:
                kind, text = probe(cam, n)
                print('  %-28s [%-4s] %s' % (n, kind, text))

        print()
        print('=' * 72)
        print('包大小对齐提醒：GevSCPSPacketSize 必须满足 (值-220) %% 8 == 0，否则 0x80000102')
        print('=' * 72)
    finally:
        cam.MV_CC_CloseDevice()
        cam.MV_CC_DestroyHandle()
        MvCamera.MV_CC_Finalize()
    return 0


if __name__ == '__main__':
    sys.exit(main())
