#!/bin/sh
# start_cam.sh —— 在板子上后台起摄像头→HDMI 常驻推流（2026-10-14）
# 用法： sh /root/start_cam.sh [帧数]    默认 20000 帧（约 30 分钟）
N=${1:-20000}
pkill -f "[c]am_to_hdmi" >/dev/null 2>&1
sleep 1
rm -f /root/cam.log
setsid nohup python3 -u /root/cam_to_hdmi.py --dev 1 --frames "$N" > /root/cam.log 2>&1 < /dev/null &
sleep 6
echo "--- 进程 ---"
ps | grep "[c]am_to_hdmi" | head -2
echo "--- 日志 ---"
tail -6 /root/cam.log 2>/dev/null || echo "  日志还没出来"
