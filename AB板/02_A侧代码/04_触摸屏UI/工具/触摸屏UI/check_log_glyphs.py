#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""check_log_glyphs.py —— 把"运行期会画到屏上的文本"也纳入字体字形检查

背景：glc_ui.py 的启动自检只扫**本文件的字符串字面量**。
但失败信息里那段 `last[0][:60]` 是**从脚本日志读进来的**，自检看不见 ⇒ 豆腐块。

本脚本把脚本日志（ui_send.log 等）+ glc_ui.py 的字符取并集，逐个查字形。
"""
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT = "/root/ui_font.ttf"
SRC = "/root/glc_ui.py"
paths = sys.argv[1:] or [
    "/root/ui_send.log", "/root/ui.log",
    "/root/ui_send.sh", "/root/send_image.sh", "/root/start_ui.sh",
]

chars = set()
for p in paths + [SRC]:
    try:
        chars |= set(open(p, encoding="utf-8", errors="replace").read())
        print("  纳入 %s" % p)
    except Exception as e:
        print("  跳过 %s (%s)" % (p, e))

todo = sorted(c for c in chars if c.isprintable() and c != " ")
f = ImageFont.truetype(FONT, 28)
missing = []
for ch in todo:
    im = Image.new("L", (48, 48), 0)
    ImageDraw.Draw(im).text((4, 4), ch, font=f, fill=255)
    if not np.asarray(im).any():
        missing.append(ch)

print()
print("检查 %d 个字符，**缺字形 %d 个**：" % (len(todo), len(missing)))
for c in missing:
    print("   %r  U+%04X" % (c, ord(c)))
print("CHECK_LOG_GLYPHS_DONE")
