#!/bin/bash
# 电台恢复守候：一直轮询到电台应答为止（最多 6 分钟）
# 用法：先在板子上跑起来，**然后**去拔插电台的电源，脚本会自己报"恢复了"
cd /root || exit 1
echo "================================================================"
echo "  现在开始轮询电台（每 3 秒一次，最多 6 分钟）"
echo "  👉 请去【物理拔掉电台的电源线/USB】等 10 秒再插回来"
echo "     （注意：要断的是【电台】的电，不是板子的电）"
echo "================================================================"
for i in $(seq 1 120); do
  R=$(python3 - <<'PY' 2>/dev/null
import os,termios,time
try:
    fd=os.open("/dev/ttyUSB0",os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK)
except Exception:
    print("NOSERIAL"); raise SystemExit
a=termios.tcgetattr(fd); i,o,c,l,is_,os_,cc=a
i=o=l=0; c=termios.CS8|termios.CREAD|termios.CLOCAL
cc[termios.VMIN]=0; cc[termios.VTIME]=0
termios.tcsetattr(fd,termios.TCSANOW,[i,o,c,l,termios.B115200,termios.B115200,cc])
def dr(s):
    t0=time.time(); out=b""
    while time.time()-t0<s:
        try: x=os.read(fd,256)
        except Exception: x=b""
        if x: out+=x
        time.sleep(0.02)
    return out
dr(0.3)
os.write(fd,b"AT+FREQ?\r\n")
r=dr(1.2)
os.close(fd)
print("OK" if b"FREQ" in r else "NO")
PY
)
  if [ "$R" = "OK" ]; then
    echo ""
    echo "  ✅ 第 $i 次轮询（约 $((i*3)) 秒）：**电台活了！**"
    echo "     正在做完整自检…"
    python3 /root/radio_check.py
    echo RADIO_WATCH_DONE
    exit 0
  fi
  [ $((i % 5)) -eq 0 ] && echo "  …已等 $((i*3)) 秒，电台还没应答"
  sleep 3
done
echo ""
echo "  ❌ 等了 6 分钟仍无应答。请检查："
echo "     · 电台的电源指示灯亮不亮"
echo "     · 串口线（CH340 那头和电台那头）插紧没有"
echo "     · 电台是不是被设成了别的波特率（我们已经扫过 9600~115200）"
echo RADIO_WATCH_TIMEOUT
