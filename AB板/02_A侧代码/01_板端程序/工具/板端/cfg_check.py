import os
import sys
from ctypes import byref, memset, sizeof

os.environ['MVCAM_SDK_PATH'] = '/opt/MVS'
os.environ['MVCAM_COMMON_RUNENV'] = '/opt/MVS/lib'
sys.path.insert(0, '/opt/MVS/Samples/aarch64/Python/MvImport')
from MvCameraControl_class import *      # noqa

d = MV_CC_DEVICE_INFO_LIST()
MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE, d)
print('n=', d.nDeviceNum)
c = MvCamera()
c.MV_CC_CreateHandle(d.pDeviceInfo[0].contents)
opened = False
for _ in range(8):
    if c.MV_CC_OpenDevice(MV_ACCESS_Control, 0) == 0:
        opened = True
        break
    import time
    time.sleep(1.5)
print('open(Control)=', opened)
if not opened:
    c.MV_CC_DestroyHandle()
    sys.exit(1)


def gi(n):
    st = MVCC_INTVALUE_EX()
    memset(byref(st), 0, sizeof(st))
    return st.nCurValue if c.MV_CC_GetIntValueEx(n, st) == 0 else None


def ge(n):
    st = MVCC_ENUMVALUE()
    memset(byref(st), 0, sizeof(st))
    return st.nCurValue if c.MV_CC_GetEnumValue(n, st) == 0 else None


print('Width=%s Height=%s OffsetX=%s OffsetY=%s'
      % (gi('Width'), gi('Height'), gi('OffsetX'), gi('OffsetY')))
print('PixelFormat=%#x' % (ge('PixelFormat') or 0))
print('PayloadSize=%s' % gi('PayloadSize'))
print('FrameRate=%s' % gi('AcquisitionFrameRate'))
c.MV_CC_CloseDevice()
c.MV_CC_DestroyHandle()
