#!/bin/bash
# ui_test14.sh —— 验证底栏提示不压快门 + 发送状态右对齐不溢出
cd /root
python3 -u /root/glc_ui.py --dev 1 -v --sleep-after 0 --script "\
sleep 4000; dump; \
tap 105,544; sleep 2500; dump; \
tap 137,155; sleep 1000; \
tap 520,552; sleep 6000; dump; \
quit"
