import ctypes
import os
import sys
import time
from ctypes import byref, memset, sizeof

os.environ['MVCAM_SDK_PATH'] = '/opt/MVS'
os.environ['MVCAM_COMMON_RUNENV'] = '/opt/MVS/lib'
sys.path.insert(0, '/opt/MVS/Samples/aarch64/Python/MvImport')
from MvCameraControl_class import *      # noqa

PKT = 1472          # MTU 1500 - 20(IP) - 8(UDP)

d = MvCC_DEVICE_INFO_LIST() if False else MV_CC_DEVICE_INFO_LIST()
MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE, d)
c = MvCamera()
c.MV_CC_CreateHandle(d.pDeviceInfo[0].contents)
ok = False
for _ in range(8):
    if c.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0) == 0:
        ok = True
        break
    time.sleep(1.5)
print('open(Exclusive)=', ok)
if not ok:
    sys.exit(1)


def gi(n):
    st = MVCC_INTVALUE_EX()
    memset(byref(st), 0, sizeof(st))
    return st.nCurValue if c.MV_CC_GetIntValueEx(n, st) == 0 else None


print('before: GevSCPSPacketSize =', gi('GevSCPSPacketSize'), ' GevSCPD =', gi('GevSCPD'))
r = c.MV_CC_SetIntValue('GevSCPSPacketSize', PKT)
print('set %d -> ret=%#x' % (PKT, r & 0xFFFFFFFF))
# 包变小了，包数变多，适当减小包间隔（GevSCPD 单位是"包间延时的 tick"）
r2 = c.MV_CC_SetIntValue('GevSCPD', 0)
print('set GevSCPD=0 -> ret=%#x' % (r2 & 0xFFFFFFFF))
print('after : GevSCPSPacketSize =', gi('GevSCPSPacketSize'), ' GevSCPD =', gi('GevSCPD'))

# 存进相机，避免下次重新上电又变回 8164
c.MV_CC_SetEnumValue('UserSetSelector', 1)
print('UserSetSave ret=%#x' % (c.MV_CC_SetCommandValue('UserSetSave') & 0xFFFFFFFF))
time.sleep(2)
c.MV_CC_CloseDevice()
c.MV_CC_DestroyHandle()
print('done')
