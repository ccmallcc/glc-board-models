#!/bin/bash
# ui_test5.sh —— 休眠寄存器采样用的驱动脚本（--sleep-after 6 s）
cd /root
python3 -u /root/glc_ui.py --dev 1 -v --sleep-after 6 --script "\
sleep 4000; state; \
sleep 6000; \
sleep 6000; \
tap 512,300; sleep 6000; state; \
sleep 8000; \
quit"
