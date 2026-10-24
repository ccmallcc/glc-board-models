#!/bin/bash
# ui_test6.sh —— 验证后台取帧线程：真实帧率 + 是否还有旧帧堆积
cd /root
python3 -u /root/glc_ui.py --dev 1 -v --sleep-after 0 --script "sleep 14000; state; dump; sleep 2000; quit"
