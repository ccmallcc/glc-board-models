#!/bin/bash
# 判定：--at-only 退出、串口关闭再重新打开之后，电台**还在不在透传模式**？
#
# 判据：透传模式下 AT 命令不会被解释 => 发 AT+FREQ? 应当**没有回应**。
#       如果重开串口把它踢出了透传 => 会回 "FREQ:470.110MHz OK"。
#
# 这个测试不需要 B 端配合。
cd /root || exit 1

echo "############ 步骤 1：--at-only（清缓冲 + 自检 + 进透传）############"
S=$(date +%s)
python3 /root/A_send_session.py --at-only 2>&1 | sed 's/^/  /'
RC=$?; E=$(date +%s)
echo "  rc=$RC  耗时 $((E-S)) s"
if [ $RC -ne 0 ]; then echo "  !! --at-only 失败，测试中止"; exit 1; fi

echo
echo "############ 步骤 2：模拟编码耗时（睡 8 秒）############"
sleep 8
echo "  已睡 8 s"

echo
echo "############ 步骤 3：重新打开串口，发 AT+FREQ? 看有没有回应 ############"
python3 - <<'PY'
import os, termios, time, sys
DEV = '/dev/ttyUSB0'
BAUDMAP = {115200: termios.B115200}
fd = os.open(DEV, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
a = termios.tcgetattr(fd)
iflag, oflag, cflag, lflag, ispeed, ospeed, cc = a
iflag = oflag = lflag = 0
cflag = termios.CS8 | termios.CREAD | termios.CLOCAL
ispeed = ospeed = termios.B115200
cc[termios.VMIN] = 0
cc[termios.VTIME] = 0
termios.tcsetattr(fd, termios.TCSANOW, [iflag, oflag, cflag, lflag, ispeed, ospeed, cc])
try:
    termios.tcflush(fd, termios.TCIOFLUSH)
except Exception:
    pass

# 先看有没有残留数据
def drain(secs):
    t0 = time.time(); out = b''
    while time.time() - t0 < secs:
        try:
            c = os.read(fd, 512)
        except (BlockingIOError, OSError):
            c = b''
        if c: out += c
        time.sleep(0.02)
    return out

pre = drain(0.5)
os.write(fd, b'AT+FREQ?\r\n')
resp = drain(1.5)
print('  重开串口后的残留数据: %r' % pre[:60])
print('  发 AT+FREQ? 的回应  : %r' % resp[:80])
if b'FREQ' in resp:
    print('  ==> ❌ **被踢出透传了**（命令被解释）—— 并行方案不可行')
    verdict = 'BROKEN'
else:
    print('  ==> ✅ **仍在透传**（命令没被解释）—— 并行方案可行')
    verdict = 'OK'

# 收尾：退出透传，恢复到命令行模式
os.write(fd, b'AT+EXIT=1\r\n')
tail = drain(1.5)
print('  收尾 AT+EXIT=1 -> %r' % tail[:60])
os.close(fd)
print('  VERDICT=%s' % verdict)
PY
echo AT_PARALLEL_TEST_DONE
