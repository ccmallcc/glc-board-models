#!/bin/bash
# ui_test4.sh —— 验证「无操作熄屏 + 关摄像头，触摸唤醒」
# --sleep-after 0：8 秒没操作就该睡。脚本里用 sleep 10000 把它等到点。
cd /root
python3 -u /root/glc_ui.py --dev 1 -v --sleep-after 0 --script "\
sleep 3000; state; dump; \
sleep 9000; state; dump; \
tap 512,300; sleep 4000; state; dump; \
sleep 9000; state; dump; \
tap 100,300; sleep 4000; state; dump; \
quit"
