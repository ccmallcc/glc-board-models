#!/bin/bash
# ui_test1.sh —— 触摸屏 UI 无人值守自测序列
# 全部通过 glc_ui.py 的 --script 走**和真人点击完全相同的代码路径**：
#   tap X,Y  = 往触摸事件队列里塞 down+up（和 /dev/input/event0 进来的一样）
#   state    = 打印内部状态
#   dump     = 把当前 canvas 原样写成 PNG（= 屏幕截图）
cd /root
python3 -u /root/glc_ui.py --dev 1 -v --script "\
sleep 3000; state; dump; \
tap 86,214; sleep 1400; state; dump; \
tap 512,546; sleep 2000; state; dump; \
tap 105,544; sleep 3000; state; dump; \
tap 137,155; sleep 1000; state; dump; \
tap 520,552; sleep 17000; state; dump; \
tap 932,23; sleep 2000; state; dump; \
quit"
