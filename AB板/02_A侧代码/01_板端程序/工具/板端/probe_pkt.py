import os
import sys
import time
from ctypes import byref, memset, sizeof

os.environ['MVCAM_SDK_PATH'] = '/opt/MVS'
os.environ['MVCAM_COMMON_RUNENV'] = '/opt/MVS/lib'
sys.path.insert(0, '/opt/MVS/Samples/aarch64/Python/MvImport')
from MvCameraControl_class import *      # noqa

d = MV_CC_DEVICE_INFO_LIST()
MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE, d)
c = MvCamera()
c.MV_CC_CreateHandle(d.pDeviceInfo[0].contents)
ok = False
for _ in range(8):
    if c.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0) == 0:
        ok = True
        break
    time.sleep(1.5)
print('open=', ok)
if not ok:
    sys.exit(1)


def gi(n):
    st = MVCC_INTVALUE_EX()
    memset(byref(st), 0, sizeof(st))
    if c.MV_CC_GetIntValueEx(n, st) == 0:
        return (st.nCurValue, st.nMin, st.nMax, st.nInc)
    return None


print('cur:', gi('GevSCPSPacketSize'))
for v in (1400, 1444, 1460, 1472, 1476, 1500, 2000, 3000, 4000, 6000):
    r = c.MV_CC_SetIntValue('GevSCPSPacketSize', v)
    now = gi('GevSCPSPacketSize')
    print('try %5d -> ret=%#010x  now=%s' % (v, r & 0xFFFFFFFF, now[0] if now else '?'))
    if r == 0:
        break
c.MV_CC_CloseDevice()
c.MV_CC_DestroyHandle()
