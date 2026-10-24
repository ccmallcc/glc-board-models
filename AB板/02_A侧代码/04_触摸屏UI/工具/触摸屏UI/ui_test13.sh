#!/bin/bash
# ui_test13.sh —— 顶栏两按钮复测（--sleep-after 10，留足时间让点击落在醒着的时候）
#   关键要看：设了"永不待机"之后，超过 10 s 也不睡
cd /root
python3 -u /root/glc_ui.py --dev 1 -v --sleep-after 10 --sleep-blackout 4 --script "\
sleep 3000; state; \
tap 972,23; sleep 1200; state; \
sleep 11000; state; dump; \
tap 972,23; sleep 800; state; \
tap 876,23; sleep 1500; state; dump; \
tap 512,300; sleep 4000; state; \
tap 105,544; sleep 2500; state; dump; \
quit"
