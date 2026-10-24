#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""make_ui_font.py —— 为触摸屏 UI 做一个极小的中文字体子集

背景（实测）：板子上 `/usr/share/fonts/truetype/dejavu/` 只有 DejaVu 系列，
**没有任何中文字形**；而 cv2.putText 的 Hershey 字体也只有 ASCII。
所以要在 1024x600 屏上写中文，必须自己带一个含中文字形的字体文件。

选字：**Noto Sans SC**（Google，SIL Open Font License 1.1）—— 许可允许再分发与子集化。
本机有 `C:\Windows\Fonts\Noto Sans SC (TrueType).otf`（8,482,020 B 静态实例）
和 `C:\Windows\Fonts\NotoSansSC-VF.ttf`（17,773,244 B 可变字体）。
这里取**静态 OTF** 做子集，只保留 ui_text.txt 里出现的字符，
产出 `ui_font.ttf`（glyf 轮廓，FreeType 兼容性最好）。

用法（用本机 E:\fudanwei\envs\glc\python.exe 跑）：
    python make_ui_font.py --src "C:\Windows\Fonts\Noto Sans SC (TrueType).otf" \
                           --text ui_text.txt --out ui_font.ttf
"""
import argparse
import os
import sys

from fontTools import subset
from fontTools.ttLib import TTFont


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=r"C:\Windows\Fonts\Noto Sans SC (TrueType).otf")
    ap.add_argument("--text", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                   "ui_text.txt"))
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                  "ui_font.ttf"))
    ap.add_argument("--scan", default="", nargs="*",
                    help="额外从这些 .py 里扫出**字符串字面量**用到的字符"
                         "（比手写 ui_text.txt 靠谱：UI 上出现的字一个都不会漏）")
    a = ap.parse_args()

    if not os.path.exists(a.src):
        raise SystemExit("找不到源字体 %s" % a.src)
    txt = open(a.text, encoding="utf-8").read()
    chars = {c for c in txt}
    if a.scan:
        import ast
        base = os.path.dirname(os.path.abspath(__file__))
        for p in a.scan:
            fp = p if os.path.isabs(p) else os.path.join(base, p)
            if not os.path.exists(fp):
                print("!! --scan 找不到 %s，跳过" % fp)
                continue
            tree = ast.parse(open(fp, encoding="utf-8").read())
            got = set()
            for n in ast.walk(tree):
                if isinstance(n, ast.Constant) and isinstance(n.value, str):
                    got |= set(n.value)
            chars |= got
            print("扫描字面量: %-14s +%d 字符" % (os.path.basename(fp), len(got)))
    # ★ 空格一定要留！上一版把 isspace() 全滤掉了，结果屏上每个空格都成了"豆腐块"
    chars |= set(" \t")
    chars = sorted(c for c in chars if c.isprintable() or c == " ")
    print("源字体 : %s  (%d B)" % (a.src, os.path.getsize(a.src)))
    print("字符数 : %d" % len(chars))

    font = TTFont(a.src, fontNumber=0)
    print("源格式 : %s  tables=%d  sfntVersion=%s"
          % ("CFF/OTF" if "CFF " in font else "glyf/TTF",
             len(font.keys()), font.sfntVersion))

    # ★★ 权威判据：直接查**源字体的 cmap**，看每个字到底有没有轮廓。
    #   绝不能用"渲染一下看有没有像素" —— 缺字形时 fontTools 会保留 .notdef 轮廓
    #   （opts.notdef_outline=True），那也"有像素" ⇒ 假阴性。
    #   2026-10-15 实测教训：就是这个假阴性让 墙/钟/耗/非 一路通过自检，用户先看见了豆腐块。
    src_cmap = set(font.getBestCmap().keys())
    absent = sorted(c for c in chars if ord(c) not in src_cmap)
    if absent:
        print("!! 源字体里没有这 %d 个字的字形（子集后会变 .notdef 方框）：" % len(absent))
        print("   %s" % "".join(absent))
        print("   ⇒ 这些字**不要用在屏上**；或换一个覆盖更全的源字体。")
    else:
        print("源覆盖 : %d 个字符源字体全都有 ✓" % len(chars))

    opts = subset.Options()
    opts.flavor = None                     # 输出 .ttf（若源是 CFF，fontTools 会保留 CFF 表）
    opts.desubroutinize = True
    opts.drop_tables += ["DSIG", "BASE", "vhea", "vmtx", "VORG"]
    opts.no_hinting = True
    opts.notdef_outline = True
    opts.recalc_bounds = True
    opts.glyph_names = False
    opts.legacy_kern = False

    sub = subset.Subsetter(options=opts)
    sub.populate(text="".join(chars))
    sub.subset(font)

    font.save(a.out)
    print("产出   : %s  (%d B)" % (a.out, os.path.getsize(a.out)))

    # 自检：能不能真的渲染中文
    try:
        from PIL import Image, ImageDraw, ImageFont
        import numpy as np
        f = ImageFont.truetype(a.out, 32)
        im = Image.new("L", (400, 44), 0)
        d = ImageDraw.Draw(im)
        d.text((2, 2), "拍照 图库 曝光 发送", font=f, fill=255)
        arr = np.asarray(im)
        print("自检   : 渲染 400x44 非零像素 = %d  (bbox=%s)"
              % (int((arr > 0).sum()), d.textbbox((2, 2), "拍照 图库 曝光 发送", font=f)))
        if (arr > 0).sum() < 200:
            raise SystemExit("!! 自检失败：渲染出来几乎是空白")
        im.save(os.path.join(os.path.dirname(a.out), "ui_font_selftest.png"))

        # ★ 逐字覆盖率自检：每个要用的字符单独渲染一遍，凡是渲染不出笔画的都报出来。
        #   上一版漏掉空格和一堆汉字，屏上就变成一个个"豆腐块"（□里一个叉），
        #   光看代码是发现不了的，必须这样查。
        # ★★ 复核：查**输出字体的 cmap**（权威判据）。
        #   绝不能用"渲染一下看有没有非零像素" —— 缺字形时 .notdef 轮廓也有像素 ⇒ 假阴性。
        #   源字体本来就没有的字（emoji 之类）这里只警告不报错：变不出来，只能保证不画它。
        out_cmap = set(TTFont(a.out).getBestCmap().keys())
        miss = sorted(c for c in chars if ord(c) not in out_cmap)
        if miss:
            print("!! 子集后仍有 %d 个字符没有字形（**这些字绝不能画到屏上**）: %s"
                  % (len(miss), "".join(miss)))
            print("   ⇒ glc_ui.py 的 txt() 里有运行期兜底：没字形的字符会被换成 '?'，")
            print("     不会出现豆腐块；但正式文案里请用普通汉字/ASCII。")
        else:
            print("覆盖率 : %d 个字符 cmap 全部命中 ✓" % len(chars))
    except ImportError:
        print("自检   : 本机没有 PIL，跳过")


if __name__ == "__main__":
    main()
