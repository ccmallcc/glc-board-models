#!/bin/bash
# wait_cam.sh —— 等网口相机上线，然后重启整条链（抓帧 + UI）
#
# 为什么需要它：2026-10-22 现场排查发现"相机不在板子的网口上"，
# 换线期间板子已经启动完了，开机脚本那一次尝试早就过去。
# 这个脚本让"插上线"这一个动作就能自动恢复，不用再敲命令。
#
# 判据：eth0 carrier=1 **连续 3 次**（约 6 s 稳定）才动手，
#       避免插头接触瞬间抖一下就把链路重启一遍。
# 日志：/root/wait_cam.log
LOG=/root/wait_cam.log
: > "$LOG"
echo "wait_cam start $(date)" >> "$LOG"

ok=0
for i in $(seq 1 200); do          # 200 × 3 s = 最多等 10 分钟
  c=$(cat /sys/class/net/eth0/carrier 2>/dev/null)
  if [ "$c" = "1" ]; then
    ok=$((ok + 1))
  else
    ok=0
  fi
  if [ "$ok" -ge 3 ]; then
    echo "carrier stable at $(date) (i=$i)" >> "$LOG"
    break
  fi
  sleep 3
done

if [ "$ok" -lt 3 ]; then
  echo "timeout: eth0 carrier never stable" >> "$LOG"
  exit 1
fi

# 报文级再确认一次（不要求一定通：相机 IP 可能变了，抓帧进程自己会枚举）
if ping -c1 -W1 169.254.104.121 >/dev/null 2>&1; then
  echo "ping 169.254.104.121 OK" >> "$LOG"
else
  echo "ping 169.254.104.121 FAILED (camera may have another IP; grabber will enumerate)" >> "$LOG"
fi

echo "restarting chain ..." >> "$LOG"
bash /root/start_ui_gige.sh >> "$LOG" 2>&1
echo "chain rc=$?" >> "$LOG"
