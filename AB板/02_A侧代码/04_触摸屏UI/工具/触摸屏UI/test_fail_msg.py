#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""test_fail_msg.py —— 用 glc_ui 自己的渲染路径把"发送失败"文案画出来，直接看有没有豆腐块

为什么：启动自检只扫 glc_ui.py 的字面量；失败文案里那段是**运行期从脚本日志读的**。
本脚本把几种真实可能出现的失败文案按 UI 的实际字号画到画布上并导出 PNG。
"""
import importlib.util
import sys

import cv2
import numpy as np

spec = importlib.util.spec_from_file_location("g", "/root/glc_ui.py")
m = importlib.util.module_from_spec(spec)
sys.modules["g"] = m
spec.loader.exec_module(m)
m.FONT_PATH = "/root/ui_font.ttf"

MSGS = [
    "失败 rc=7 对方未确认 41s | [UI] 全部墙钟 41 s",
    "失败 rc=7 对方未确认 41s | [SS] 对方始终没确认 BEGIN，放弃（容器没发出去）",
    "失败 rc=7 对方未确认 41s | [SS]   SESSION_BEGIN 第 3/3 次：无应答（6.00 s）—— 4 s 后重试",
    "失败 rc=3 电台自检没过 8s | [AT] [SS] AT 自检一次性耗时 8.24 s",
    "失败 rc=6 编码失败 5s | [ENC] 编码器返回非 0",
    "失败 rc=4 没找到容器 2s | [UI] 没找到 .glc 容器",
    "发送完成 3s（已空口发出）",
    "已编码(GLC) 2s — 无电台未发射",
    "发送中 12s · 等对方应答 BEGIN 3",
]

cv = np.zeros((600, 1024, 3), np.uint8)
y = 34
for s in MSGS:
    m.txt(cv, s, 12, y, 17)
    y += 62
cv2.imwrite("/root/test_fail_msg.png", cv)

print("=== 每行用到的字符（含码位）===")
seen = set()
for s in MSGS:
    for ch in s:
        if ch.isprintable() and ch != " " and ch not in seen:
            seen.add(ch)
print("  共 %d 个不同可打印字符" % len(seen))
print("TEST_FAIL_MSG_DONE")
