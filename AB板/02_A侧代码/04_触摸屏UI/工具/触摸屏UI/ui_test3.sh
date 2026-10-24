#!/bin/bash
# ui_test3.sh —— 验证"发送中"阶段的进度显示（含等对方 ACK 的倒计时）
# B 端现在不在监听，所以这次注定会走到"失败 rc=7 对方未确认" —— 正好把失败路径也验了。
cd /root
python3 -u /root/glc_ui.py --dev 1 -v --script "\
sleep 2500; dump; \
tap 105,544; sleep 2500; dump; \
tap 137,155; sleep 1200; dump; \
tap 520,552; sleep 13000; dump; \
sleep 12000; dump; \
sleep 28000; state; dump; \
quit"
