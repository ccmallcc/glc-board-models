#!/bin/bash
# ui_test8.sh —— 验证待机提示：--sleep-after 6，不关显示输出（提示应一直可见）
cd /root
python3 -u /root/glc_ui.py --dev 1 -v --sleep-after 6 --sleep-blackout 0 --script "\
sleep 4000; state; dump; \
sleep 6000; state; dump; \
tap 512,300; sleep 4000; state; dump; \
quit"
