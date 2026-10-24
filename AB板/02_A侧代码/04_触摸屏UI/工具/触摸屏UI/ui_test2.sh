#!/bin/bash
# ui_test2.sh —— 第二轮自测：重点压"最重的路径"
#   ① 相机在跑 + 屏幕在刷 + NPU + PL rANS 同时工作时的「发送最新」
#   ② 图库翻页
cd /root
python3 -u /root/glc_ui.py --dev 1 -v --script "\
sleep 3000; state; dump; \
tap 86,274; sleep 900; state; dump; \
tap 512,546; sleep 2500; state; dump; \
tap 919,544; sleep 18000; state; dump; \
tap 105,544; sleep 2500; state; dump; \
tap 276,552; sleep 1500; state; dump; \
tap 100,552; sleep 1500; state; dump; \
tap 932,23; sleep 1500; state; dump; \
quit"
