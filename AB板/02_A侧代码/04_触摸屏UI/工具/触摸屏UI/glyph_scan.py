#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""glyph_scan.py —— 正确的字形自检：用 .notdef 比对，而不是"有没有画出东西"

★ 为什么原来的判据是错的（2026-10-15 实测）：
  旧判据 = 把字符渲染到空图上，看 `np.asarray(im).any()`。
  但**缺字形时 PIL 画的是 .notdef 方框** —— 那也"画出了东西" ⇒ 判成"有字形" ⇒ **假阴性**。
  所以"墙/钟/耗/非"缺字形却一路通过了自检，直到用户看见豆腐块。

新判据：先渲染一个**私用区码位**（U+E123，字体里必然没有）拿到 .notdef 位图，
        任何字符的位图与它**完全相同** ⇒ 该字符缺字形。

用法: python3 glyph_scan.py [文件...]
"""
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT = "/root/ui_font.ttf"
DEFAULT = ["/root/glc_ui.py", "/root/ui_send.sh", "/root/send_image.sh",
           "/root/start_ui.sh", "/root/ui.log", "/root/ui_send.log"]


def mask_bytes(f, ch):
    im = Image.new("L", (64, 64), 0)
    ImageDraw.Draw(im).text((6, 6), ch, font=f, fill=255)
    return np.asarray(im).tobytes()


def main():
    f = ImageFont.truetype(FONT, 28)
    ref = mask_bytes(f, "\ue123")          # 私用区 ⇒ 必然缺字形 ⇒ 这就是 .notdef 的样子
    blank = mask_bytes(f, " ")
    print("字体 = %s" % FONT)
    print("  .notdef 位图非空 = %s ；空白位图非空 = %s"
          % (any(ref), any(blank)))

    files = sys.argv[1:] or DEFAULT
    chars = set()
    for p in files:
        try:
            chars |= set(open(p, encoding="utf-8", errors="replace").read())
        except Exception as e:
            print("  跳过 %s (%s)" % (p, e))
    todo = sorted(c for c in chars if c.isprintable() and c != " ")

    missing = []
    for ch in todo:
        mb = mask_bytes(f, ch)
        if mb == ref or not any(mb):
            missing.append(ch)

    print("\n扫描 %d 个字符，**真·缺字形 %d 个**：" % (len(todo), len(missing)))
    for c in missing:
        print("   %r  U+%04X" % (c, ord(c)))
    print("\n（旧判据只会报出其中「PIL 完全不画」的那几个）")
    print("GLYPH_SCAN_DONE")


if __name__ == "__main__":
    main()
