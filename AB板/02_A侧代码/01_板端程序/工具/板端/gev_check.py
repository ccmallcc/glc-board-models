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
    if c.MV_CC_OpenDevice(MV_ACCESS_Control, 0) == 0:
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
        return (st.nCurValue, st.nMin, st.nMax)
    return None


for node in ('GevSCPSPacketSize', 'GevSCPD', 'GevSCPSBigEndian',
             'GevSCPSDoNotFragment', 'GevHeartbeatTimeout', 'PayloadSize'):
    print('%-24s %s' % (node, gi(node)))

# 宿主机 MTU（用来对照）
try:
    for line in open('/sys/class/net/eth0/mtu'):
        print('eth0 MTU =', line.strip())
except Exception as e:
    print('mtu read fail', e)
c.MV_CC_CloseDevice()
c.MV_CC_DestroyHandle()
