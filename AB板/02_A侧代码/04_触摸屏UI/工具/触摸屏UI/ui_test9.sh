#!/bin/bash
# ui_test9.sh —— 验证"待机立即关显示输出"（--sleep-after 6，blackout 0 = 立即关）
cd /root
python3 -u /root/glc_ui.py --dev 1 -v --sleep-after 6 --sleep-blackout 0 --script "\
sleep 4000; state; \
sleep 6000; state; dump; \
tap 512,300; sleep 5000; state; \
quit"
