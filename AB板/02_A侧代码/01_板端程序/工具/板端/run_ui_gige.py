#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_ui_gige.py —— 用"网口相机"跑原版 glc_ui.py（不改 UI 一行）

做的事：
  1. 装 gige_shim（把 cv2.VideoCapture 换成读 /dev/shm 的假相机）
  2. 组好 sys.argv：--dev /dev/gigecam + 原来的待机参数
  3. 用 compile(filename) + exec 跑 glc_ui.py，**并补齐 __file__**（缺它会崩在 check_font_coverage）

用法：
  python3 run_ui_gige.py                 # 默认 --sleep-after 90 --sleep-blackout 10
  python3 run_ui_gige.py --fg            # 同前台（无实际差别，都是前台）
  GLC_UI_SLEEP=0 python3 run_ui_gige.py  # 永不待机
"""
import os
import sys

UI = '/root/glc_ui.py'
SHIM = '/root/gige_shim.py'

sleep = os.environ.get('GLC_UI_SLEEP', '90')
blackout = os.environ.get('GLC_UI_BLACKOUT', '10')

# 让 gige_shim 能被 import（同一个目录）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gige_shim            # noqa: E402
gige_shim.install()

sys.argv = ['glc_ui.py', '--dev', '/dev/gigecam', '-v',
            '--sleep-after', sleep, '--sleep-blackout', blackout]
print('[run_ui_gige] argv =', ' '.join(sys.argv), flush=True)

src = open(UI, encoding='utf-8').read()
code = compile(src, UI, 'exec')          # 用真实文件名编译 ⇒ 报错行号/__file__ 都对
g = {'__name__': '__main__', '__file__': UI, '__builtins__': __builtins__}
exec(code, g)
