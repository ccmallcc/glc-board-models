#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""glc_ui.py —— GLC 触摸屏交互界面：拍照 + 图库 + 发送（HDMI 1024x600）

=============================================================================
 这个程序干什么
=============================================================================
在一块 FMQL100TAI（Zynq-7030 级）板上，把 **1024x600 HDMI 屏 + 电阻/电容触摸屏 +
USB 摄像头** 组成一个可触摸操作的拍照/发送终端：

    屏幕 = PS 往 PL 的 udma 保留内存写 RGB565，PL 按 1024x600@59.52Hz 扫描出去
    触摸 = /dev/input/eventN（wch.cn USB2IIC_CTP_CONTROL, 1a86:e5e3）
           ★ **不要写死 eventN** —— 实测重启后它会从 event0 变成 event1
             （摄像头自带 kbd 句柄会抢走 event0），而且**不报错、只是不响应**。
             现在用 resolve_touch() 按 /proc/bus/input/devices 里的设备名解析（--touch auto，默认）。
    相机 = /dev/videoN（HD 720P Webcam, 0c45:6341, UVC 1.00, MJPG）
           ★ **不要写死 index** —— 实测重启后它会从 video1 变成 video0。
             现在用 resolve_cam() 按「Card type 含 Webcam + Device Caps 有 Video Capture
             且无 Metadata Capture」自动解析（--dev auto，默认）。

  ┌─ 拍照界面 ────────────────────────────────────────────────┐
  │  GLC 拍照                                       已拍 12 张 │
  │ ┌──────┐                                    ┌───────────┐ │
  │ │ 曝光 │        ┌──────────────────┐        │ 分辨率    │ │
  │ │ EV   │        │                  │        │ 640x480   │ │
  │ │ +0.75│        │   实时预览       │        │ MJPG      │ │
  │ │  ▓▓  │        │   610x458        │        │ 12.5 fps  │ │
  │ │  ▓▓  │        │                  │        │           │ │
  │ │ [-]  │        └──────────────────┘        │ 状态      │ │
  │ │ [+]  │                                    │ 就绪      │ │
  │ │ AUTO │                                    │           │ │
  │ └──────┘                                    └───────────┘ │
  │  [ 图库 ]            (  快门  )            [ 发送最新 ]    │
  └────────────────────────────────────────────────────────────┘
  ┌─ 图库界面 ────────────────────────────────────────────────┐
  │  GLC 图库  第 1/2 页                    [ 返回拍照 ]        │
  │  ┌────┐ ┌────┐ ┌────┐ ┌────┐                              │
  │  │IMG │ │IMG │ │IMG │ │IMG │   点一下选中（蓝框）          │
  │  └────┘ └────┘ └────┘ └────┘                              │
  │  ┌────┐ ┌────┐ ┌────┐ ┌────┐                              │
  │  └────┘ └────┘ └────┘ └────┘                              │
  │  [上一页][下一页] [ 发送选中 ]      状态文字…              │
  └────────────────────────────────────────────────────────────┘

=============================================================================
 ★ 关于"调曝光"—— 一个必须先说清楚的实测结论
=============================================================================
这块摄像头的 UVC 控制项**全是摆设**。实测（/root/gain_test.py，2026-10-14）：

    gain        0 → 100      帧均值 85.86 → 85.60   （变化 0.3%）
    brightness  -64 → +64    帧均值 85.99 → 86.10   （变化 0.1%）
    backlight_compensation 0→2  85.99 → 85.65

而且它**根本没有曝光控制项**：
    `v4l2-ctl -C exposure_absolute` → `unknown control 'exposure_absolute'`
    （exposure_auto / exposure_time_absolute / exposure_auto_priority 同样 unknown）
    `v4l2-ctl --list-ctrls` 只有 brightness/contrast/saturation/hue/gamma/gain/
    power_line_frequency/sharpness/backlight_compensation —— **没有 exposure_***。

⇒ 自动曝光是相机固件自己在做，我们碰不到；那些能碰的旋钮又都是空壳。
⇒ 所以本程序的"曝光调节"是 **PS 侧的数字曝光补偿（EV）**：
      lut = clip(round(px * 2**EV), 0, 255)，用 cv2.LUT 查表，预览与存盘**同一套**。
   这是真的在调曝光（调完按快门，存下来的照片就是调过的），只是调在数字域。
   UI 上标注为「曝光 EV（数字）」，不冒充硬件曝光。

另外提供 **AUTO 软件自动曝光**：统计帧均值，按 0.12 EV/帧 的慢速率朝目标
（均值 112）逼近，死区 ±3，范围 ±3 EV。这是板子自己实现的 AE，和固件那套无关。

=============================================================================
 命令行
=============================================================================
    python3 glc_ui.py                          # 正常跑
    python3 glc_ui.py --dev 1 --ev 0.0
    python3 glc_ui.py --script "tap 512,546; sleep 2500; dump; quit"
                                                # 无人工干预地跑一段操作序列（自测用）
    kill -USR1 <pid>                            # 把当前 canvas 原样存成 /root/ui_dump.png
                                                #   ← 这是"屏幕截图"，用来核对屏上到底画了什么

=============================================================================
 性能（实测，A9@~1GHz，见 62 号文档）
=============================================================================
    cap.read()  取帧   62.6 ms ← 瓶颈：相机实际只送 ~16 fps（标称 30）
    LUT 曝光 + 缩放     ~5 ms
    RGB565 转换        31.4 ms
    写 udma             0.9 ms（1.34 GB/s）
    ⇒ 端到端 ~10 fps。写帧缓冲从来不是瓶颈。
"""
import argparse
import errno
import math
import os
import queue
import select
import signal
import struct
import subprocess
import sys
import threading
import time

import numpy as np

# ----------------------------------------------------------------- 常量
W, H = 1024, 600
BUF = W * H * 2
DISPLAY_READ_ADDR = 0x40080054
VTC_ENABLE = 0x400800B4
DISPLAY_ENABLE = 0x40080018
# ★ HDMI 同步门控（slv_reg30）。RTL 里 `display_en = ~disable_hdmi_2`，而 display_en 直接
#   门控 `timing_hs/vs/de = color_bar_hs/vs/de & display_en` ⇒ 写 1 会把 HS/VS/DE 全部拉掉。
#   显示器因此**丢掉同步 → 进待机 → 背光真正熄灭**（用户 2026-10-15 实测确认）。
#   只关 0x18(img_en) 是不够的：那只关"图像"，TMDS 照常跑，显示器一直认为信号有效，
#   于是背光一直亮着 —— 这就是"熄屏后背光板还亮"的原因。
HDMI_DISABLE = 0x40080078


def _uptime():
    """开机后秒数。板子没有 RTC，日志里的墙钟每次开机都从同一个值开始，只有 uptime 能对比。"""
    try:
        with open('/proc/uptime') as f:
            return float(f.read().split()[0])
    except Exception:
        return -1.0
DEV_URL = "axi://zg330aiu?npu=0x40000000&dma=0x80000000"

TOP_H, BOT_H = 46, 96
PY0, PY1 = TOP_H, H - BOT_H            # 预览区上下边 46..504（高 458）
PANEL = (10, 56, 162, 494)             # 左曝光面板
INFOX = (830, 1014)                    # 右侧信息栏

PHOTO_DIR = "/root/photos"
# 相册子目录（2026-10-15 加）：快门拍的图仍在 PHOTO_DIR 根下，**导入的图放这里**。
# 图库分成「相机 / 相册」两屏就是按这两个位置分的 —— 拷图进 album/ 即出现在「相册」。
ALBUM_DIR = "/root/photos/album"
FONT_PATH = "/root/ui_font.ttf"
SEND_SH = "/root/ui_send.sh"
SEND_LOG = "/root/ui_send.log"
RADIO = "/dev/ttyUSB0"
DUMP_PATH = "/root/ui_dump.png"

SLEEP_HINT = "待机中，轻触屏幕唤醒"
SLEEP_COUNTDOWN = "待机中，%d 秒后将关闭显示"

EV_MIN, EV_MAX, EV_STEP = -3.0, 3.0, 0.25
AE_TARGET, AE_RATE, AE_DEAD = 112.0, 0.12, 3.0

# ===== 硬件曝光（GigE 相机，MV-CE013-50GC）=====
# 为什么要有这一套：上面那套数字 EV 是给**旧的 USB UVC 相机**写的，
# 那台相机的 v4l2 曝光控制项根本不存在，只能靠 PS 侧提亮。
# 换成 GigE 相机后，ExposureTime / Gain 是真能调的硬件节点，
# 所以这里走 gige_grab.py 的控制通道（/dev/shm/gigecam.ctl|stat）。
# 拿不到通道（例如又插回 USB 相机）时，自动退回数字 EV，行为与以前一致。
EXP_MIN, EXP_MAX = 50.0, 1000000.0      # µs，相机节点范围待枚举确认
FPS_FLOOR = 15.0                        # ★ 帧率下限（用户 2026-10-20 定，原为 10）
EXP_CEIL_US = 1000000.0 / FPS_FLOOR     # 曝光硬上限 = 1/15 s ≈ 66.7 ms
EXP_DEFAULT = 15000.0                   # ★ 复位目标 = 15 ms（用户 2026-10-20 定；正好是挡位之一）
EXP_START_US = 50000.0                  # ★ 开机初始曝光 = 50 ms（用户 2026-10-22 定，原 60）
EXP_LADDER_TOP = 60000.0                # ★ 挡位塔顶仍是 60 ms（= 15 fps 下的硬上限 60 ms）
EXP_STOP_RATIO = 0.5                    # 60 / 30 / 15 / 7.5 / 3.75 / 1.875 ...
# ★ 2026-10-21 删掉 `EXP_STEP_EV = 1/6`：它从未被任何代码读过（死常量），
#   而注释写着"每按一次 1/6 档"，会让人以为曝光能微调 —— 实际不能。
#   曝光的真实粒度就是"挡位塔 11 档"：滑条吸附挡位、`-`/`+` 整档 x2 / x0.5。
#   用户 2026-10-21 明确选"只删常量、不改行为"，所以没有改成 1/6 档。
GAIN_MIN, GAIN_MAX, GAIN_STEP = 0.0, 24.0, 3.0   # ★ 增益 dB，每次增减 3 dB（用户 2026-10-20 定）
GAIN_DEFAULT = 14.0                             # ★ 初始/复位值 14 dB
WB_MIN, WB_MAX, WB_STEP = -1.0, 1.0, 0.1        # 白平衡冷暖轴，单位"档"（2 的幂）
WB_BASE = 1024.0                               # 通道比例基准 = 1.0x
CLIP_HI = 250                           # 任一通道 >= 250 记作"高光裁剪"
CLIP_TARGET = 0.005                     # 信息栏"高光"变红的阈值（显示用）
CLIP_AE_LIMIT = 0.015                   # ★ Q11-#12：AE 真正用的"过曝急刹"阈值
CTL_F = "/dev/shm/gigecam.ctl"
STAT_F = "/dev/shm/gigecam.stat"
REQ_F = "/dev/shm/gigecam.req"        # 请求抓帧进程读回白平衡比值
RATIOS_F = "/dev/shm/gigecam.ratios"  # "Red=.. Green=.. Blue=.."


def fmt_ms(us):
    """µs -> ms 的**显示**文本。>=10 ms 用 1 位小数，<10 ms 用 2 位。

    因为挡位是 60/30/15/7.5/3.75/1.875…，到低档位时 1 位小数会撞车
    （0.9 / 0.5 / 0.2 / 0.1 / 0.1），所以低于 10 ms 改用 2 位。
    """
    ms = float(us) / 1000.0
    return ("%.1f" % ms) if ms >= 10.0 else ("%.2f" % ms)


def hw_set_many(pairs):
    """一次写多条节点命令。**必须一次写**：抓帧进程每轮循环只读一次 ctl 文件，
    分两次写会让前一条被后一条覆盖（这是 2026-10-20 实测踩过的坑）。
    gige_grab 侧已改成按行遍历，所以多行文件它会一条条按顺序执行。
    """
    try:
        tmp = CTL_F + ".tmp"
        with open(tmp, "w", encoding="ascii") as f:
            for name, val in pairs:
                f.write(u"%s %s\n" % (name, val))
        os.replace(tmp, CTL_F)
        return True
    except OSError:
        return False


def hw_stat():
    """读抓帧进程公布的当前曝光/增益。读不到返回 {}（= 没有硬件控制）。"""
    try:
        with open(STAT_F, "r", encoding="ascii", errors="replace") as f:
            d = {}
            for kv in f.read().split():
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    try:
                        d[k] = float(v)
                    except ValueError:
                        pass
            return d
    except OSError:
        return {}


def hw_set(name, val):
    """把一条节点写入丢给抓帧进程。写临时文件再 rename，避免读到半行。"""
    try:
        tmp = CTL_F + ".tmp"
        with open(tmp, "w", encoding="ascii") as f:
            f.write(u"%s %s\n" % (name, val))
        os.replace(tmp, CTL_F)
        return True
    except OSError:
        return False

# ui_send.sh 发 ASCII 状态码，中文文案在这里（本文件的字面量 ⇒ 会被启动时的字体覆盖率自检扫到）
STAGE_TEXT = {
    "READY":  "电台已就绪",
    "AT":     "起 AT 自检（并行）",
    "ENC":    "GLC 编码中（引擎常驻）",
    "ATWAIT": "等自检收尾",
    "SEND":   "等对方应答",
}


def BGR(r, g, b):
    """参数按 R,G,B 写；返回 OpenCV / numpy 画布用的 BGR。"""
    return (b, g, r)


PAL = {
    "bg":       BGR(16, 17, 21),
    "bar":      BGR(30, 33, 42),
    "bar2":     BGR(24, 26, 33),
    "btn":      BGR(58, 63, 78),
    "btn_ed":   BGR(90, 97, 116),
    "hi":       BGR(38, 112, 196),
    "ok":       BGR(36, 148, 88),
    "bad":      BGR(184, 56, 48),
    "dis":      BGR(42, 44, 52),
    "txt":      BGR(236, 239, 245),
    "dim":      BGR(146, 152, 164),
    "dim2":     BGR(96, 101, 112),
    "accent":   BGR(255, 176, 48),
    "gray":     BGR(150, 152, 158),      # 待机提示用的灰
    "white":    BGR(255, 255, 255),
    "black":    BGR(0, 0, 0),
}


# ----------------------------------------------------------------- 文字（PIL TTF -> 贴图缓存）
_font_cache = {}
_tile_cache = {}


def _font(size):
    f = _font_cache.get(size)
    if f is None:
        from PIL import ImageFont
        f = ImageFont.truetype(FONT_PATH, size)
        _font_cache[size] = f
    return f


# ----------------------------------------------------------------- 字形兜底
# ★★ 为什么要有这一层（2026-10-15 第三次豆腐块事故）：
#   启动自检只扫**本文件的字符串字面量**；但屏幕上的失败信息里有一段是
#   **运行期从脚本日志读进来的**（`last[0][:60]`）—— 自检根本看不见它。
#   所以再加一道**运行期**闸门：画之前逐字查字形，没有的就换成 '?'。
_GLYPH_CACHE = {}
_NOTDEF = [None]
_MISSING_DRAWN = []


def _glyph_missing(ch):
    r"""这个字在字体里到底有没有字形？

    判据（旧判据是错的，见 check_font_coverage 的说明）：
      用一个必然不存在的码位（U+E123，私用区）渲染出 .notdef 的样子；
      任何字符的位图与它**完全相同** ⇒ 缺字形。
    """
    v = _GLYPH_CACHE.get(ch)
    if v is not None:
        return v
    from PIL import Image, ImageDraw
    f = _font(28)
    if _NOTDEF[0] is None:
        im = Image.new("L", (64, 64), 0)
        ImageDraw.Draw(im).text((6, 6), "\ue123", font=f, fill=255)
        _NOTDEF[0] = np.asarray(im).tobytes()
    im = Image.new("L", (64, 64), 0)
    ImageDraw.Draw(im).text((6, 6), ch, font=f, fill=255)
    mb = np.asarray(im).tobytes()
    v = (mb == _NOTDEF[0]) or (not mb.strip(b"\x00"))
    _GLYPH_CACHE[ch] = v
    if v:
        _MISSING_DRAWN.append(ch)
        print("!! 屏上要画 %r (U+%04X) 但字体没字形 —— 已画成 '?'" % (ch, ord(ch)),
              flush=True)
    return v


_ANSI = __import__("re").compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def sanitize(s):
    """画之前的最后一道闸：剥 ANSI 转义、把没字形的字换成 '?'。

    为什么需要：`send_msg` 末尾那段是脚本日志原文（可能带 ❌ / 生僻字 / 颜色码），
    启动自检看不见它。没有这一层，屏上就会出现豆腐块。
    """
    if not s:
        return s
    s = _ANSI.sub("", s)
    out = []
    for c in s:
        if c == " " or c == "\t":
            out.append(c)
        elif not c.isprintable():
            out.append(" ")            # \r \n \x1b 之类一律拍成空格
        elif _glyph_missing(c):
            out.append("?")
        else:
            out.append(c)
    return "".join(out)


def text_size(s, size=22):
    from PIL import Image, ImageDraw
    if not s:
        return (0, 0)
    s = sanitize(s)
    f = _font(size)
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    l, t, r, b = d.textbbox((0, 0), s, font=f)
    return (max(0, r - l), max(0, b - t))


STAT = {"tile": 0, "miss": 0, "blit_px": 0, "blit": 0}


def _tile(s, size, color):
    STAT["tile"] += 1
    key = (s, size, color)
    t = _tile_cache.get(key)
    if t is not None:
        return t
    STAT["miss"] += 1
    from PIL import Image, ImageDraw
    f = _font(size)
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    l, t_, r, b = d.textbbox((0, 0), s, font=f)
    w, h = max(1, r - l), max(1, b - t_)
    im = Image.new("L", (w, h), 0)
    ImageDraw.Draw(im).text((-l, -t_), s, font=f, fill=255)
    a = np.asarray(im).copy()
    rgb = np.empty((h, w, 3), np.uint8)
    rgb[:] = color
    t = (rgb, a, w, h)
    _tile_cache[key] = t
    return t


def blit(canvas, rgb, a, x, y):
    """alpha 混合贴图；只处理 alpha>0 的像素（UI 小贴图，够快）"""
    h, w = a.shape
    ch, cw = canvas.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(cw, x + w), min(ch, y + h)
    if x0 >= x1 or y0 >= y1:
        return
    STAT["blit"] += 1
    aa = a[y0 - y:y1 - y, x0 - x:x1 - x]
    m = aa > 0
    STAT["blit_px"] += int(m.sum())
    if not m.any():
        return
    sub = canvas[y0:y1, x0:x1]
    al = aa[m].astype(np.uint16)[:, None]
    s = sub[m].astype(np.uint16)
    c = rgb[y0 - y:y1 - y, x0 - x:x1 - x][m].astype(np.uint16)
    sub[m] = ((s * (255 - al) + c * al) // 255).astype(np.uint8)


def fit_txt(canvas, s, x, y, max_w, size=18, color=None, anchor="lt"):
    r"""画一行文字，**保证不超过 max_w 宽**：先自动缩字号，再截断加「…」。

    为什么需要：底栏状态行的左右两侧都有硬边界（中间是快门圆 x 472~552），
    文字一长就会压上去叠在一起 —— 实测踩过。宁可缩小/截断，也不能压。
    """
    if not s:
        return
    for sz in (size, size - 1, size - 2, size - 3):
        if text_size(s, sz)[0] <= max_w:
            txt(canvas, s, x, y, sz, color, anchor)
            return
    sz = max(12, size - 3)
    t = s
    while t and text_size(t + "…", sz)[0] > max_w:
        t = t[:-1]
    txt(canvas, (t + "…") if t else "", x, y, sz, color, anchor)


def txt(canvas, s, x, y, size=22, color=None, anchor="lt"):
    """anchor: 两个字符，第1个 l/c/r（左右），第2个 t/m/b（上下）"""
    if not s:
        return
    s = sanitize(s)          # ★ 运行期兜底：没字形的字换成 '?'，绝不画成豆腐块
    color = color or PAL["txt"]
    rgb, a, w, h = _tile(s, size, color)
    ax, ay = anchor[0], anchor[1]
    px = x if ax == "l" else (x - w if ax == "r" else x - w // 2)
    py = y if ay == "t" else (y - h if ay == "b" else y - h // 2)
    blit(canvas, rgb, a, px, py)


# ----------------------------------------------------------------- 画图小工具
def rrect(cv, box, color, r=12, fill=True, thick=2):
    import cv2
    x0, y0, x1, y1 = box
    r = max(0, min(r, (x1 - x0) // 2, (y1 - y0) // 2))
    if fill:
        cv2.rectangle(cv, (x0 + r, y0), (x1 - r, y1), color, -1)
        cv2.rectangle(cv, (x0, y0 + r), (x1, y1 - r), color, -1)
        for cx, cy in ((x0 + r, y0 + r), (x1 - r, y0 + r), (x0 + r, y1 - r), (x1 - r, y1 - r)):
            cv2.circle(cv, (cx, cy), r, color, -1)
    else:
        cv2.line(cv, (x0 + r, y0), (x1 - r, y0), color, thick)
        cv2.line(cv, (x0 + r, y1), (x1 - r, y1), color, thick)
        cv2.line(cv, (x0, y0 + r), (x0, y1 - r), color, thick)
        cv2.line(cv, (x1, y0 + r), (x1, y1 - r), color, thick)
        for cx, cy, a0 in ((x0 + r, y0 + r, 180), (x1 - r, y0 + r, 270),
                           (x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90)):
            cv2.ellipse(cv, (cx, cy), (r, r), a0, 0, 90, color, thick)


def button(cv, box, label, size=24, bg=None, fg=None, edge=None):
    x0, y0, x1, y1 = box
    rrect(cv, box, bg or PAL["btn"], r=10, fill=True)
    if edge:
        rrect(cv, (x0, y0, x1, y1), edge, r=10, fill=False, thick=2)
    txt(cv, label, (x0 + x1) // 2, (y0 + y1) // 2, size, fg or PAL["txt"], "cm")


# ----------------------------------------------------------------- 后台取帧
def resolve_cam(spec="auto"):
    r"""把"摄像头设备"解析成一个**稳定的**节点路径。

    ★ 为什么必须这样（2026-10-15 实测踩到）：
      写死 index 在**重启后会错**。同一条 USB 摄像头，重启前是 `/dev/video1`，
      重启后变成 `/dev/video0`（Linlon 硬编解码节点也参与枚举竞争，顺序会变）。
      表现：屏上「无信号 / 相机未打开」，日志刷 `can't open camera by index`。

    ★ 判据（实测有效）：`v4l2-ctl -d /dev/videoN --info`
        Card type   : 含 "Webcam"
        Device Caps : 那一段里**有** "Video Capture" 且**没有** "Metadata Capture"

      ⚠ 坑：`--info` 顶部还会再印一遍驱动的**总能力**（"Video Capture" 和
         "Metadata Capture" **两行都在**）。**必须只看 "Device Caps :" 之后那一段**，
         否则两个节点都会被误判成采集节点。实测三个节点：
             video0  Card=HD 720P Webcam  Device Caps 段 = Video Capture      -> 采集 ✓
             video1  Card=HD 720P Webcam  Device Caps 段 = Metadata Capture   -> metadata ✗
             video2  Card=Linlon Video device  (名字不是 webcam)              -> ✗

    spec:
        "auto" / "" / None  -> 自动找（推荐）
        "/dev/videoN"       -> 直接用，不解析
        "3" / 3             -> 先自动找；找不到再退回这个 index（向后兼容旧的 --dev 1）
    """
    if isinstance(spec, str) and spec.startswith("/dev/"):
        return spec

    def probe(path):
        try:
            p = subprocess.run(["v4l2-ctl", "-d", path, "--info"],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               timeout=5)
            out = p.stdout.decode("utf-8", "replace")
        except Exception:
            return None, None
        card = ""
        for ln in out.splitlines():
            if "Card type" in ln:
                card = ln.split(":", 1)[1].strip()
                break
        seg = out.split("Device Caps", 1)
        return card, (seg[1] if len(seg) > 1 else "")

    for n in range(0, 12):
        p = "/dev/video%d" % n
        if not os.path.exists(p):
            continue
        card, dc = probe(p)
        if card is None:
            continue
        if (("webcam" in card.lower() or "camera" in card.lower())
                and "Video Capture" in dc and "Metadata Capture" not in dc):
            print("  摄像头自动解析: %s  (%s)" % (p, card), flush=True)
            return p

    try:
        idx = int(spec)
    except Exception:
        idx = 0
    print("  !! 自动解析没找到摄像头，回退到 index %d（v4l2-ctl 可用吗？）" % idx, flush=True)
    return idx


class CamGrab(threading.Thread):
    r"""后台连续取帧，**永远只保留最新的一帧**。

    为什么必须这样（全部实测，2026-10-15）：
      · 相机标称 30 fps，但 `v4l2-ctl --stream-mmap` 实测驱动只能到 19 fps 上下，
        `cap.read()` 单次中位 **78.9 ms**（≈12.5 fps），而且分辨率完全无关
        （640x480 / 640x360 / 432x240 全是 12.5 fps ⇒ 不是带宽、不是解码）
      · 但 UI 主循环里 `cap.read()` 只占 **27.5 ms** —— 比相机出帧还快！
        ⇒ 说明 read() 拿的是**驱动缓冲里的旧帧**，不是刚出的新帧
      · 旧帧 = 延迟。屏上画面比现实晚「缓冲深度 × 80 ms」，这才是"卡"的手感来源，
        跟"帧率"是两回事。
    后台线程把驱动缓冲一直抽干，渲染线程只取最新那张 ⇒ 延迟降到约 1 帧，
    而且取帧和渲染解耦，渲染慢一点也不会堆积旧帧。
    """

    def __init__(self, dev, cw, ch, fps_req=0):
        super(CamGrab, self).__init__(daemon=True)
        self.dev, self.cw, self.ch, self.fps_req = resolve_cam(dev), cw, ch, fps_req
        self.lock = threading.Lock()
        self.frame = None
        self.has_new = False        # 已解码、等消费者来取
        self.seq = 0
        self.stop = False
        self.ok = False
        self.err = ""
        self.cap = None
        self.rate = 0.0             # 解码/交付速率（≈ 渲染速率）
        self.grab_rate = 0.0        # 驱动侧抽帧速率（相机真实出帧能力）
        self.total = 0
        self.n_grab = 0
        self._n = 0
        self._ng = 0
        self._t0 = time.time()
        self.real_wh = (0, 0)

    def open(self):
        import cv2
        cap = cv2.VideoCapture(self.dev)
        if not cap.isOpened():
            self.err = "%s 打不开" % self.dev
            return False
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.cw)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.ch)
        if self.fps_req:
            cap.set(cv2.CAP_PROP_FPS, self.fps_req)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        for _ in range(3):
            cap.read()
        self.cap = cap
        self.real_wh = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                        int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        self.ok = True
        return True

    def run(self):
        r"""★ 关键：**只用 grab() 抽干驱动队列，不在这里解码**。

        第一版这里写的是 `cap.read()`（= grab + 解码），实测**把主循环饿死了**：
          取帧线程拿了 190 帧、解码 190 次（每次 ~30 ms CPU），
          而主循环只迭代了 94 次 ⇒ 屏上只有 5.9 fps，比相机的 12.5 还低一半。
        而且 190 次解码里有 96 次是白解的（消费者根本用不上）。

        改成：grab() 只从驱动取走缓冲（不解码，~50 ms 一次，几乎不占 CPU），
        驱动队列因此一直是空的 ⇒ **不会堆旧帧、延迟低**；
        只有消费者把上一帧取走了，才 retrieve() 解码这一帧 ⇒ 解码次数 = 渲染次数。
        """
        if not self.open():
            return
        while not self.stop:
            if not self.cap.grab():
                time.sleep(0.002)
                continue
            self.n_grab += 1
            with self.lock:
                busy = self.has_new
            if busy:
                continue          # 上一帧还没被取走：这帧丢掉（队列照样被抽干）
            ok, f = self.cap.retrieve()
            if not ok:
                continue
            with self.lock:
                self.frame = f
                self.has_new = True
                self.seq += 1
            self._n += 1
            self._ng += 1
            self.total += 1
            now = time.time()
            if now - self._t0 >= 1.0:
                self.rate = self._n / (now - self._t0)
                self.grab_rate = self._ng / (now - self._t0)
                self._n = self._ng = 0
                self._t0 = now

    def take(self):
        """消费者取走最新帧。取走后取帧线程才会去解码下一帧。"""
        with self.lock:
            if not self.has_new:
                return None, self.seq
            self.has_new = False
            return self.frame, self.seq

    def close(self):
        self.stop = True
        try:
            self.join(timeout=2.0)
        except Exception:
            pass
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        self.ok = False


# ----------------------------------------------------------------- 触摸
def resolve_touch(spec="auto"):
    r"""把"触摸屏设备"解析成一个**稳定的** /dev/input/eventN。

    ★ 为什么必须这样（2026-10-15 实测踩到，与相机是同一个病）：
      写死 eventN 在**重启后会错**。同一条 USB 触摸屏（1a86:e5e3），
      重启前是 `/dev/input/event0`，重启后变成 **`event1`** ——
      因为那个 USB 摄像头（HD 720P Webcam）**自带 kbd 句柄**，抢走了 event0。

      症状特别隐蔽：**设备能正常打开、不报任何错**，只是永远收不到 ABS 事件
      ⇒ 屏幕上点哪儿都没反应，看日志也看不出问题。

    判据：读 `/proc/bus/input/devices`，找 Name 含 "USB2IIC_CTP" / "wch.cn" 的块，
          取它 `H: Handlers=` 里的 eventN。

    spec:
        "auto" / "" / None  -> 自动找（推荐）
        "/dev/input/eventN" -> 直接用，不解析
    """
    if spec and spec != "auto":
        return spec
    default = "/dev/input/event0"
    try:
        txt = open("/proc/bus/input/devices", encoding="utf-8", errors="replace").read()
    except Exception as e:
        print("  !! 读不到 /proc/bus/input/devices: %s，回退 %s" % (e, default), flush=True)
        return default

    for block in txt.split("\n\n"):
        name, handlers = "", ""
        for ln in block.splitlines():
            if ln.startswith("N: Name="):
                name = ln.split("=", 1)[1].strip().strip('"')
            elif ln.startswith("H: Handlers="):
                handlers = ln.split("=", 1)[1]
        if not name or not handlers:
            continue
        low = name.lower()
        if not ("usb2iic_ctp" in low or "wch.cn" in low or "ctp_control" in low):
            continue
        for tok in handlers.split():
            if tok.startswith("event") and tok[5:].isdigit():
                p = "/dev/input/" + tok
                print("  触摸屏自动解析: %s  (%s)" % (p, name), flush=True)
                return p

    print("  !! 自动解析没找到触摸屏（1a86:e5e3 插着吗？），回退 %s" % default, flush=True)
    return default


class Touch(threading.Thread):
    r"""/dev/input/eventN -> 语义事件队列（down / move / up）

    实测（EVIOCGABS）：ABS_X 与 ABS_Y 的 min=0 max=4096
        => px = x*W//4096, py = y*H//4096
    BTN_TOUCH(0x14a) 按下/抬起；ABS_MISC(0x28) 出现=第二指（这里忽略）。
    """
    EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
    ABS_X, ABS_Y, ABS_MISC = 0, 1, 0x28
    BTN_TOUCH = 0x14A
    FMT = struct.Struct("llHHi")        # 64 位 struct input_event = 24 B

    def __init__(self, dev="auto", q=None):
        super(Touch, self).__init__(daemon=True)
        self.spec = dev                     # ★ 留原始参数：重开时要拿它重新解析
        self.dev = resolve_touch(dev)
        self.q = q or queue.Queue()
        self.stop = False
        self.ok = False
        self.err = ""
        self.n_down = 0
        self.last = (0, 0)
        self.last_t = 0.0
        self.is_down = False
        self.raw = (0, 0)
        self.misc = 0
        self.n_reopen = 0                   # 重开次数（诊断/自测用）
        self.last_reopen = 0.0

    # ---------------------------------------------------------------- 设备生命周期
    def _open(self):
        """打开当前 self.dev；失败返回 None 并把原因记在 self.err。"""
        try:
            fd = os.open(self.dev, os.O_RDONLY | os.O_NONBLOCK)
            self.err = ""
            return fd
        except OSError as e:
            self.err = str(e)
            return None

    def _same_device(self, fd):
        r"""fd 指向的还是不是 self.dev 现在指的那个设备？

        ★★ 这是本补丁的核心判据 —— **只比路径名不够**：
          触摸屏重新枚举后，路径**还是** `/dev/input/event0`（名字一模一样！），
          但那个 /dev 节点已经换成新的 inode 了；旧 fd 变成 `(deleted)`
          （`ls -l /proc/<pid>/fd` 里能看见），**读它永远读不到东西**。

        实测（2026-10-15，用户按复位键之后）：dmesg 里触摸屏 6 次
        `USB disconnect` + 重新枚举，而 UI 一直攥着第一次打开的 event0，
        表现是"**屏上点哪儿都没反应，但零报错**" —— 因为
        `os.read` 抛的 OSError 被 `continue` 吞了，线程还活着。

        所以判据要落到 **inode**：`os.stat(路径).st_ino == os.fstat(fd).st_ino`。
        路径没了、fd 失效，都算"不是同一个"。
        """
        try:
            return os.stat(self.dev).st_ino == os.fstat(fd).st_ino
        except OSError:
            return False

    def _reopen(self, why):
        """关旧 fd → 重新解析路径 → 再打开。成功返回新 fd，失败返回 None。"""
        # 重新解析很重要：重枚举后可能连路径都变了
        #（实测摄像头会抢走 event0，触摸屏从 event0 变成 event1）
        self.dev = resolve_touch(self.spec)
        fd = self._open()
        self.n_reopen += 1
        self.last_reopen = time.time()
        self.ok = (fd is not None)
        # 设备换了 ⇒ 之前"手指按着"的状态全部作废，否则会卡在按下态
        self.is_down = False
        print("  [触摸] 重新打开%s：%s（原因：%s）"
              % ("成功" if fd is not None else "失败", self.dev, why), flush=True)
        return fd

    def run(self):
        fd = self._open()
        if fd is None:
            print("!! 打不开 %s: %s（每 2 秒重试）" % (self.dev, self.err), flush=True)
        else:
            self.ok = True
        x = y = 0
        down = False
        sent_down = False
        lastpos = (-1, -1)
        next_check = time.time() + 2.0      # 下次"设备还在不在"体检的时刻
        while not self.stop:
            # ---- 没有可用 fd：退避重试（不要忙等）----
            if fd is None:
                time.sleep(2.0)
                fd = self._reopen("设备不可用，重试")
                if fd is not None:
                    x = y = 0
                    down = False
                    sent_down = False
                    lastpos = (-1, -1)
                    next_check = time.time() + 2.0
                continue

            r, _, _ = select.select([fd], [], [], 0.2)

            # ---- ★ 每 2 秒体检：设备是否已被重新枚举（同名换 inode）----
            #      放在 select 之后、read 之前，这样"没数据"的常态下也能查出来。
            now = time.time()
            if now >= next_check:
                next_check = now + 2.0
                if not self._same_device(fd):
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    fd = None
                    self.ok = False
                    print("  [触摸] 设备已重新枚举（路径同名但 inode 变了）⇒ 重开", flush=True)
                    continue

            if not r:
                continue
            try:
                data = os.read(fd, self.FMT.size * 64)
            except OSError as e:
                # EAGAIN/EWOULDBLOCK = select 说可读但读时又没数据了；EINTR = 被信号打断。
                # **这两个不是"设备没了"** —— 为它们重开会把正在按下的手指状态清掉，
                # 表现成"滑到一半突然断了"。
                if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EINTR):
                    continue
                try:
                    os.close(fd)
                except OSError:
                    pass
                fd = None
                self.ok = False
                print("  [触摸] 读失败(%s) ⇒ 重开" % e, flush=True)
                continue
            for off in range(0, len(data) - self.FMT.size + 1, self.FMT.size):
                _, _, typ, code, val = self.FMT.unpack_from(data, off)
                if typ == self.EV_ABS:
                    if code == self.ABS_X:
                        x = val
                    elif code == self.ABS_Y:
                        y = val
                    elif code == self.ABS_MISC:
                        self.misc = val
                elif typ == self.EV_KEY and code == self.BTN_TOUCH:
                    down = (val != 0)
                    self.is_down = down
                elif typ == self.EV_SYN:
                    px = min(W - 1, max(0, x * W // 4096))
                    py = min(H - 1, max(0, y * H // 4096))
                    self.raw = (x, y)
                    if down and not sent_down:
                        sent_down = True
                        lastpos = (px, py)
                        self.n_down += 1
                        self.last = (px, py)
                        self.last_t = time.time()
                        self.q.put(("down", px, py))
                    elif down and (px, py) != lastpos:
                        lastpos = (px, py)
                        self.last = (px, py)
                        self.last_t = time.time()
                        self.q.put(("move", px, py))
                    elif (not down) and sent_down:
                        sent_down = False
                        self.q.put(("up", px, py))
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


# ----------------------------------------------------------------- 主 UI
class UI(object):
    def __init__(self, a):
        self.a = a
        self.screen = "cam"
        self.ev = a.ev
        self.auto = a.auto
        # 硬件曝光状态（hw_ok 由第一帧时探测：拿得到 gigecam.stat 才算有）
        self.exp_us = float(getattr(a, "exp_us", EXP_DEFAULT))
        self.hwstat = {}            # ★ 不要叫 self.stat —— 那是性能计时字典，已被占用
        self.hw_ok = False
        self.clip = 0.0
        self._stat_t = 0.0
        self._ae_t = 0.0
        self._auto_off = False      # 是否已经给相机发过 ExposureAuto=Off
        self._init_done = False     # 首次接触相机时做一次性初始化
        self.exp_shown = 0.0        # 屏上**当前画着**的曝光值（用来判断是否需要重画）
        self._init_step = 0         # 初始化状态机：一帧只发一条 ctl
        # 三模式：曝光 / 增益 / 白平衡（按钮切换，滑块与加减都作用于当前模式）
        # ★ 2026-10-22 用户定（方案 A）：**上电默认停在「增益」**，先看到增益项。
        self.mode = "gain"
        # 发送尺寸：False=小图（中心裁 256）、True=大图（512 切 4 块 256，一个会话 N=4/MODE=1）
        self.img_big = False
        self.g_auto = False
        self.w_auto = False
        self.wb = 0.0               # 白平衡冷暖轴，-1..+1 档
        self._awb_until = 0.0       # 一次性 AWB 的截止时刻
        # 白平衡基线：AWB 收敛后相机自己的 R/G/B 比值，手动档在它上面做乘性微调。
        # 不读回的话手动一发绝对值就把自动结果覆盖了（实测画面跳回偏绿）。
        self.wb_base = (WB_BASE, WB_BASE, WB_BASE)
        self._rwb_t = 0.0
        self.q = queue.Queue()
        self.touch = Touch(a.touch, self.q)
        self.stop = False
        self.dirty = True
        self.canvas = np.zeros((H, W, 3), np.uint8)
        self.canvas[:] = PAL["bg"]
        # ★ 常驻 RGB565 缓冲：**只重算变了的矩形**，其余保留上一帧的值。
        #   全屏转换 614400 px 实测要 64 ms；预览矩形 610x458=279380 px 只要 ~29 ms。
        #   稳态（没有交互）时每帧只转预览矩形，省掉 35 ms/帧。
        self.u16 = np.zeros((H, W), np.uint16)
        self.ov_prev = False
        self.prev_rect = None
        self.regions = []            # [(name, x0,y0,x1,y1)] 当前屏热区
        self.drag = None             # 正在拖的控件名
        self.drag_box = None
        self.down_at = (0, 0)
        self.down_t = 0.0
        self.down_name = None
        self.flash_until = 0.0
        self.toast = ""
        self.toast_until = 0.0
        self.shot_pending = False
        self.last_frame = None       # 最近一帧（已做 EV 的 BGR）
        self.n_shot = 0
        self.fps = 0.0
        self.frames = 0
        self.t_fps = time.time()
        self.cap = None
        self.grab = None            # 后台取帧线程（CamGrab）
        self.last_seq = -1          # 上一帧的序号，用来判断"有没有新帧"
        self.chunk = None
        self.reg = None
        self.gal_page = 0
        self.gal_sel = None         # （保留：旧代码/脚本里可能引用；新逻辑用 self.queue）
        # ---- 发送队列（2026-10-15 加）----
        #   self.queue  = **选中待发**的图片路径，**顺序 = 点击顺序**，可跨「相机/相册」两栏混选。
        #   发送时由 start_queue() 顺序逐张跑 ui_send.sh（一次只跑一个进程）。
        self.queue = []
        self.send_q = []            # 正在跑的这一队列（快照）
        self.send_i = 0             # 当前发到第几张（0 基）
        self.send_ok = 0            # 本队列已成功张数
        self.send_bad = []          # [(path, rc, why), ...]
        self.send_skip = []         # 被跳过的损坏产物序号（1 基），用于收尾汇报
        self.clear_until = 0.0      # 「清空」的二次确认窗口
        self.thumbs = {}
        self.photos = []
        # ---- 图库分两组（2026-10-15）----
        #   相机 = /root/photos/ 根目录下（快门拍的，do_shot 写这里）
        #   相册 = /root/photos/album/（导入的图，直接拷进去即可）
        #   两组各自**按文件名升序**排 —— 不要按 mtime，那不是"顺序"。
        self.gal_tab = 0            # 0=相机 1=相册
        self.groups = []            # [(key, 中文名, [(path, mtime, size), ...]), ...]
        self.latest = None          # mtime 最大的那张 —— 「发送最新」用它，
                                    # ★ 升序排列后不能再拿 photos[0]（那是**最旧**的）
        self.n_cam = 0
        self.n_alb = 0
        self.send_proc = None
        self.send_t0 = 0.0
        self.send_path = ""
        self.send_state = "idle"     # idle|run|ok|fail
        self.send_msg = "就绪"
        self.dump_req = False
        self.dump_n = 0
        self.lock = threading.Lock()      # 渲染/推屏 与 截图 互斥（否则截图会撕裂）
        # ---- 休眠（无操作熄屏 + 关摄像头）----
        self.awake = True
        self.last_act = time.time()
        self.wake_req = False
        self.swallow = False              # 唤醒那一下的手势整段吃掉，不触发按钮
        self.n_sleep = 0
        self.sleep_t = 0.0                # 进入待机的时刻
        self.disp_on = True               # 显示输出当前是否开着
        self.sleep_never = False          # ★ 顶栏「永不待机」按钮：True = 关掉自动待机
        self.blackout_at = 0.0            # 关显示输出的时刻（0=不倒计时）
        self.count_shown = -1             # 屏上倒计时当前显示到几秒
        self.stat = {"read": 0.0, "conv": 0.0, "lut": 0.0, "push": 0.0, "n": 0}
        self.n_loop = 0
        self.n_newf = 0
        self.chrome_ok = False      # 界面静态部分（顶栏/面板/按钮）是否已经画好
        self.err = ""

    # ---------------------------------------------------------- 显示初始化
    def setup_display(self):
        from icraft import xrt
        dev = xrt.Device.Open(DEV_URL)
        self.reg = dev.defaultRegRegion()
        self.chunk = dev.getMemRegion("udma").malloc(BUF, False)
        addr = self.chunk.begin.addr()
        self.disp_addr = addr
        # ★★ 2026-10-17：**先画一屏"待机/无信号"，再开显示**。
        #   原来这里直接 `write(HDMI_DISABLE,0)` + `disp_enable(True)`，而"第一帧"要等
        #   `open_cam()` + `refresh_photos()`（实测与引擎载入抢 I/O 时能到 **7 s**）
        #   ⇒ 那 7 秒里屏上是一块**没画过的帧缓冲** = 用户看到的"亮一下蓝屏"。
        #   实测数据：开显示 13.2 s、首帧 20.1 s ⇒ 蓝了 6.9 s。
        #   现在：先 draw_standby() 把"待机中，轻触屏幕唤醒"画进缓冲，再开显示
        #   ⇒ 屏一亮就是这一屏，首帧就绪后自动换成界面。黑屏/蓝屏都没有了。
        self.disp_on = False
        try:
            self.draw_standby()
        except Exception as e:
            print("  !! 预画待机屏失败（不影响起界面）: %s" % e, flush=True)
        # ★ 2026-10-23：**先关一次再开**。开机时屏可能已经被 boot_splash 打开、
        #   且显示地址还指着它的缓冲；这里若直接"开"，本进程把地址切到自己的
        #   缓冲时，那一瞬会扫到未初始化的内存 ⇒ **花屏一闪**（用户实测）。
        #   先关显示+同步、再按原顺序打开，就只剩一次干净的重新握手。
        try:
            self.disp_enable(False)
            time.sleep(0.05)
        except Exception:
            pass
        self.disp_enable(True)
        self.disp_on = True
        print("  udma=0x%08x  0x40080054=0x%08x  显示已开：先显示待机屏，首帧就绪后换成界面  uptime=%.1fs"
              % (addr, addr >> 3, _uptime()), flush=True)

    def disp_enable(self, on):
        """开关显示输出。关掉 0x18 就是真熄屏（TMDS 停，显示器自己进待机）。
        ★ 唤醒时要把 VTC、显示使能、帧地址**三个都重写一遍** —— 只写 0x18 不够，
          实测关掉后 PL 侧的帧地址寄存器会失效，不重写得白屏。"""
        try:
            if on:
                self.reg.write(HDMI_DISABLE, 0)      # 先恢复同步（否则下面写了也不出图）
                self.reg.write(VTC_ENABLE, 1)
                self.reg.write(DISPLAY_ENABLE, 1)
                self.reg.write(DISPLAY_READ_ADDR, self.disp_addr >> 3)
            else:
                self.reg.write(HDMI_DISABLE, 1)      # ★ 关 HS/VS/DE ⇒ 显示器丢同步、进待机、背光灭
                self.reg.write(DISPLAY_ENABLE, 0)    # 顺带关图像
        except Exception as e:
            print("  !! 显示开关失败: %s" % e, flush=True)

    def open_cam(self):
        if self.grab is not None:
            return True
        g = CamGrab(self.a.dev, self.a.cw, self.a.ch, self.a.cam_fps)
        g.start()
        for _ in range(80):                 # 等它真正开起来（最多 4 s）
            if g.ok or g.err:
                break
            time.sleep(0.05)
        if g.err or not g.ok:
            self.err = g.err or "摄像头启动超时"
            g.close()
            return False
        self.grab = g
        print("  摄像头 %dx%d MJPG（后台取帧线程；请求 fps=%s）"
              % (g.real_wh[0], g.real_wh[1], self.a.cam_fps or "默认"), flush=True)
        return True

    def close_cam(self):
        if self.grab is not None:
            g, self.grab = self.grab, None
            g.close()
            self.last_frame = None
            self.last_seq = -1

    # ---------------------------------------------------------- 帧处理
    def ev_lut(self):
        k = 2.0 ** self.ev
        return np.clip(np.arange(256, dtype=np.float32) * k, 0, 255).astype(np.uint8)

    def apply_ev(self, bgr):
        import cv2
        t = time.time()
        if t - self._stat_t > 0.25:
            self._stat_t = t
            self.hwstat = hw_stat()
            # Q11-#7：抓帧进程死了以后 /dev/shm/gigecam.stat 还会留在那儿，
            #   只看"文件有没有内容"会让 hw_ok 一直 True —— 硬件写入没人执行，
            #   同时退回数字 EV 的路又被堵死。所以用 mtime 判活。
            self.hw_ok = False
            if self.hwstat:
                try:
                    # 阈值给 12 s：抓帧进程是**每 10 帧**刷一次 stat（不是按时间），
                    # 15 fps 时 ≈0.67 s，但若有人把帧率压到 1 fps 就是 10 s ——
                    # 用 2 s 会在低帧率下误判成"通道死了"而错误退回数字 EV（Q13 查出）。
                    self.hw_ok = (t - os.stat(STAT_F).st_mtime) < 12.0
                except OSError:
                    self.hw_ok = False
        # 高光裁剪率：8 bit 一旦到 255 就永久丢失，这个数就是"过没过曝"的判据
        if getattr(bgr, "ndim", 2) == 3:
            self.clip = float((bgr >= CLIP_HI).any(axis=2).mean())
        else:
            self.clip = float((bgr >= CLIP_HI).mean())
        if self.hw_ok:
            # ★ Q11-#3/#4 审计查出的两个问题，都在这里修：
            #   ① 抓帧进程**每轮循环只消费一条 ctl**（读到就 unlink），
            #      同一帧连发 2~3 条会互相覆盖、前面的直接丢 ⇒ 初始化拆成"一帧一条"。
            #   ② hw_set 返回 False 时不能假装成功，否则 _auto_off 被置 True
            #      后就再也不补发，相机会一直拒绝写曝光。
            if not self._init_done:
                if self._init_step == 0:
                    if hw_set("ExposureAuto", "Off"):
                        self._init_step = 1
                    return bgr
                if self._init_step == 1:
                    # ★ 2026-10-22 用户定（方案 A）：上电后**打开自动增益**（相机自己调），
                    #   左栏默认停在「增益」，正好看着它收敛。
                    #   用户一旦手动拖滑条/按 ±，set_gain() 会先发 GainAuto=Off 再写值，
                    #   所以"自动 → 手动"仍然可控（不会被相机一直拉回去）。
                    if hw_set("GainAuto", "Continuous"):
                        # ★ 2026-10-22 用户指出：既然上电就是自动增益，**界面上的 AUTO 按钮
                        #   必须显示为"开"** —— 否则按钮是灰的、相机却在自动调，看着自相矛盾。
                        self.g_auto = True
                        self.dirty = True
                        self._init_step = 2
                    return bgr
                self._init_step = 3
                self._auto_off = True
                self._init_done = True
                v = self.hwstat.get("ExposureTime")
                if v:
                    self.exp_us = float(v)
                self.wb_request()      # 拿一次相机当前的白平衡比值当基线
                return bgr
            if self.auto:
                self._hw_ae(float(bgr.mean()))
            if t - self._rwb_t > 1.0:
                self._rwb_t = t
                try:
                    with open(RATIOS_F) as f:
                        d = dict(kv.split("=") for kv in f.read().split())
                    nb = (float(d["Red"]), float(d["Green"]), float(d["Blue"]))
                    if all(v > 0 for v in nb):
                        self.wb_base = nb
                except (OSError, ValueError, KeyError):
                    pass
            if self.w_auto and self._awb_until and t > self._awb_until:
                self._awb_until = 0.0
                self.w_auto = False
                hw_set("BalanceWhiteAuto", "Off")   # 收敛完就锁住，不让它一直跟着环境漂
                self.wb_request()                   # 把相机收敛出的比值读回来当基线
                self.dirty = True
            return bgr                      # 硬件已经曝光过了，绝不再叠数字增益
        # ---------- 以下为回退路径：没有硬件曝光控制时，行为与旧版完全一致
        if abs(self.ev) < 1e-3 and not self.auto:
            return bgr
        if self.auto:
            m = float(bgr.mean())
            if abs(m - AE_TARGET) > AE_DEAD:
                d = AE_RATE if m < AE_TARGET else -AE_RATE
                self.ev = max(EV_MIN, min(EV_MAX, round((self.ev + d) * 4) / 4.0))
                self.dirty = True
        return cv2.LUT(bgr, self.ev_lut())

    def _hw_ae(self, mean):
        """自动曝光：**盯均值，带高光保护**。

        为什么要改（2026-10-20 22:02 板上实测，曝光扫描 2000/8000/33000 µs）：
            2000 µs → 均值 14.0，clip 0.0%，最亮 36
            8000 µs → 均值 18.1，clip 0.0%，最亮 41
           33000 µs → 均值 89.3，clip 0.0%，最亮 166
        三个点 **clip 全都是 0** —— 现场是"太暗"，根本不是"过曝"。
        所以第一版"只在 clip 超 0.5% 时降曝光"的写法永远不会动，等于没 AE。

        现在的策略：
          ① clip > 1.5%  ⇒ 过曝优先，直接砍半档（高光一旦到 255 就永久丢失）
          ② 否则按 ln2 比例朝均值 110 走，每步最多半档（防抖动）
          ③ 曝光顶到上限还不够亮，才去提增益（增益只加噪声，最后手段）
        """
        now = time.time()
        if now - self._ae_t < 0.5:
            return
        self._ae_t = now
        if self.clip > CLIP_AE_LIMIT:
            self.nudge_exp(-0.5, keep_auto=True)
            return
        if mean < 1.0:
            return
        target = 110.0
        if abs(mean - target) < 6.0:
            return
        g = self.hwstat.get("Gain", 0.0)
        if mean > target and g > GAIN_MIN + 0.4:
            # ★ 偏亮时**先降增益**：同样亮度下增益越低噪声越小、压缩越好。
            #   原来只会"曝光顶到上限还不够亮才加增益"，永远不降
            #   ⇒ 屏上增益一直卡在 20 dB 不动（用户 2026-10-20 实测发现）。
            hw_set("Gain", "%.1f" % max(GAIN_MIN, g - 1.0))
            return
        cap = self.exp_cap()
        ev = max(-0.5, min(0.5, math.log2(target / mean)))
        new_us = max(EXP_MIN, min(cap, self.exp_us * (2.0 ** ev)))
        if new_us >= cap - 1.0 and mean < target - 6.0 and g < GAIN_MAX:
            hw_set("Gain", "%.1f" % min(GAIN_MAX, g + 1.0))
            return                    # Q11-#6：这一拍只动增益，不再动曝光（防 ±1dB 往返）
        self.exp_us = round(new_us, 1)
        self.dirty = True
        self.hw_exp(self.exp_us)

    def exp_stops(self):
        """按 60 ms 起、每档 x 0.5 生成挡位表（µs，升序），只保留 <= exp_cap() 的。"""
        cap = self.exp_cap()
        out = []
        v = EXP_LADDER_TOP
        while v >= EXP_MIN:
            if v <= cap + 1e-6:
                out.append(round(v, 3))
            v *= EXP_STOP_RATIO
        if not out:
            out = [EXP_MIN]
        return sorted(out)

    def exp_step(self, up):
        """挡位切换：+ 走上一档（x2），- 走下一档（x0.5），到顶/到底就停住。"""
        stops = self.exp_stops()
        cur = max(EXP_MIN, min(self.exp_cap(), float(self.exp_us)))
        if up:
            cand = [s for s in stops if s > cur * 1.0001]
            nv = cand[0] if cand else stops[-1]
        else:
            cand = [s for s in stops if s < cur * 0.9999]
            nv = cand[-1] if cand else stops[0]
        self.exp_us = round(nv, 3)
        self.auto = False
        self.dirty = True
        self.hw_exp(self.exp_us)

    def exp_cap(self):
        """当前允许的最大曝光时间。两条硬约束：

        ① `EXP_CEIL_US = 1e6 / FPS_FLOOR` —— 用户 2026-10-20 定：**帧率不许低于 15 fps**
           ⇒ 曝光硬上限 66.7 ms（早先是 10 fps / 90 ms，用户要求收紧到 15 fps）；
        ② 曝光不许超过帧周期的 0.9 倍。

        ⚠ 更正（2026-10-20 22:40，实测）：早先这里写的是“相机把曝光上限绑在帧周期上、
           超了静默拒绝”，**那是错的**。实测相机会接受 500 ms 甚至 1000 ms，只是把
           ResultingFrameRate 降到 2.0 / 1.0。当时看起来“被拒”的真因是：连发了两条 ctl，
           而抓帧进程每轮只消费一条 —— 前一条被后一条覆盖了。
        所以②**不是相机的要求，是我们自己的策略**：宁可限曝光，也不让帧率掉下去。
        """
        cap = EXP_CEIL_US
        fps = self.hwstat.get("AcquisitionFrameRate", 0.0)
        if fps > 0.5:
            cap = min(cap, 0.9e6 / fps)
        return max(EXP_MIN, cap)

    def hw_exp(self, us):
        """写曝光时间。**先夹到 exp_cap() 内，再确保自动曝光已关**。

        ★ 为什么必须夹：相机对超周期/超范围的曝光是**静默拒绝**（ctlrep 非 0，但
          UI 原来不检查）⇒ 表现成"AE 卡住不动"或"改了曝光没反应"。与其写后回读
          （会和抓帧进程抢 ctlrep，读到上一次的值造成误判），不如从源头夹住。
        """
        if self.hw_ok and not self._auto_off:
            if hw_set("ExposureAuto", "Off"):     # Q11-#3：成功才置位，失败下帧再试
                self._auto_off = True
        us = max(EXP_MIN, min(self.exp_cap(), float(us)))
        self.exp_us = round(us, 1)
        hw_set("ExposureTime", "%.1f" % us)

    def nudge_exp(self, ev, keep_auto=False):
        """按 ev 档（可为负）改曝光时间，夹在 EXP_MIN..EXP_MAX，并写进相机。"""
        self.exp_us = max(EXP_MIN, min(self.exp_cap(), self.exp_us * (2.0 ** ev)))
        self.exp_us = round(self.exp_us, 1)
        if not keep_auto:
            self.auto = False
        self.dirty = True
        self.hw_exp(self.exp_us)

    # ---------------------------------------------------------- 事件
    def drain(self):
        while True:
            try:
                kind, x, y = self.q.get_nowait()
            except queue.Empty:
                return
            self.on_touch(kind, x, y)

    def hit(self, x, y):
        for nm, x0, y0, x1, y1 in self.regions:
            if x0 <= x <= x1 and y0 <= y <= y1:
                return nm
        return None

    def on_touch(self, kind, x, y):
        self.last_act = time.time()       # 任何触摸都算"有操作"，重置休眠计时
        if not self.awake:
            # 睡着时：这一整段手势只用于唤醒，**不触发任何按钮**
            # （否则"想唤醒"很容易变成"按到了快门"或"改了曝光"）
            self.wake_req = True
            self.swallow = True
            return
        if self.swallow:
            if kind == "up":
                self.swallow = False
            return
        if kind == "down":
            self.down_at = (x, y)
            self.down_t = time.time()
            nm = self.hit(x, y)
            self.down_name = nm
            if self.a.verbose:
                print("  DOWN (%4d,%4d) hit=%s" % (x, y, nm), flush=True)
            if nm == "slider_ev":
                self.drag = "ev"
                self.drag_box = next(b for b in self.regions if b[0] == "slider_ev")[1:]
                self.set_ev_from_y(y)
            elif nm == "gal_swipe":
                self.drag = "gal"
                self.drag_x0 = x
            self.dirty = True
        elif kind == "move":
            if self.drag == "ev":
                self.set_ev_from_y(y)
            elif self.drag == "gal":
                if abs(x - getattr(self, "drag_x0", x)) > 60:
                    self.turn_page(1 if x < self.drag_x0 else -1)
                    self.drag = None
            self.dirty = True
        elif kind == "up":
            dt = time.time() - self.down_t
            moved = abs(x - self.down_at[0]) + abs(y - self.down_at[1])
            hit = self.hit(x, y)
            # ★ 点按窗口放到 2.0 s：相机偶尔卡一下会让一帧超过 1 s，1.2 s 的窗口会把
            #   "按下"和"抬起"拆到两次 drain 里、看起来像长按，从而把这一下吞掉。
            if self.drag == "ev":
                if self.a.verbose:
                    print("  UP   (%4d,%4d) 结束滑块拖动 -> EV %+.2f" % (x, y, self.ev), flush=True)
                self.drag = None
                self.dirty = True
                return
            if self.drag == "gal":
                self.drag = None
                self.dirty = True
                return
            ok = (dt < 2.0 and moved < 40)
            if self.a.verbose:
                print("  UP   (%4d,%4d) dt=%.2f moved=%d hit=%s -> %s"
                      % (x, y, dt, moved, hit, "TAP" if ok else "丢弃(超时/移动过大)"), flush=True)
            if ok:
                self.tap(hit)
            self.dirty = True

    # -------------------------------------------------- 三模式（曝光/增益/白平衡）
    def cur_auto(self):
        return {"exp": self.auto, "gain": self.g_auto, "wb": self.w_auto}[self.mode]

    def cur_mode_text(self):
        """返回 (大数字文本, 上方小字说明)。"""
        if self.mode == "exp":
            if not self.hw_ok:
                return ("%+.2f" % self.ev, "数字 EV(回退)")
            v = float(self.hwstat.get("ExposureTime", self.exp_us))
            self.exp_shown = v          # 记下已画出去的值，供主循环比对同步
            return (fmt_ms(v), "上限" + fmt_ms(self.exp_cap()) + " ms")
        if self.mode == "gain":
            g = self.hwstat.get("Gain")
            return (("%.1f dB" % g) if g is not None else "-- dB",
                    "自动(GainAuto)" if self.g_auto else "手动 3dB")
        return ("%+.1f" % self.wb,
                "R %d / B %d" % (self.wb_base[0] * 2.0 ** self.wb,
                                  self.wb_base[2] * 2.0 ** (-self.wb)))

    def cur_frac(self):
        """当前模式在滑块上的位置 0..1（0=底 1=顶）。"""
        if self.mode == "exp":
            if not self.hw_ok:
                return max(0.0, min(1.0, (self.ev - EV_MIN) / (EV_MAX - EV_MIN)))
            stops = self.exp_stops()
            cur = float(self.hwstat.get("ExposureTime", self.exp_us))
            cur = max(stops[0], min(stops[-1], cur))
            lo, hi = math.log10(stops[0]), math.log10(stops[-1])
            return max(0.0, min(1.0, (math.log10(cur) - lo) / (hi - lo)))
        if self.mode == "gain":
            g = self.hwstat.get("Gain")
            g = GAIN_DEFAULT if g is None else float(g)
            return max(0.0, min(1.0, (g - GAIN_MIN) / (GAIN_MAX - GAIN_MIN)))
        return max(0.0, min(1.0, (self.wb - WB_MIN) / (WB_MAX - WB_MIN)))

    def set_frac(self, f):
        """滑块拖动 -> 当前模式的量。"""
        f = max(0.0, min(1.0, f))
        if self.mode == "exp":
            if not self.hw_ok:
                nv = round((EV_MIN + f * (EV_MAX - EV_MIN)) / EV_STEP) * EV_STEP
                if abs(nv - self.ev) > 1e-6:
                    self.ev = nv
                    self.auto = False
                    self.dirty = True
                return
            stops = self.exp_stops()
            lo, hi = math.log10(stops[0]), math.log10(stops[-1])
            raw = 10.0 ** (lo + f * (hi - lo))
            nv = min(stops, key=lambda z: abs(math.log10(z) - math.log10(raw)))
            if abs(nv - self.exp_us) > 1e-6:
                self.exp_us = round(nv, 3)
                self.auto = False
                self.dirty = True
                self.hw_exp(self.exp_us)
            return
        if self.mode == "gain":
            self.set_gain(GAIN_MIN + f * (GAIN_MAX - GAIN_MIN))
            return
        self.set_wb(WB_MIN + f * (WB_MAX - WB_MIN))

    def set_ev_from_y(self, y):
        _, y0, _, y1 = self.drag_box
        f = 1.0 - (float(y) - y0) / max(1.0, float(y1 - y0))
        self.set_frac(f)

    def set_gain(self, g):
        # ★ 不做全局栅格吸附：增减是"当前值 ±3 dB"，而初始值 14 dB 不是 3 的倍数，
        #   若吸附到 3 的整数倍，第一次按 + 会从 14 跳到 18（看起来像多走了一档）。
        g = round(max(GAIN_MIN, min(GAIN_MAX, float(g))), 1)
        self.g_auto = False
        self.dirty = True
        # 关自动 + 写值 一次发两条（grab 侧按行遍历，不会丢）
        hw_set_many([("GainAuto", "Off"), ("Gain", "%.1f" % g)])

    def wb_request(self):
        """请抓帧进程读回当前三个通道的 BalanceRatio（异步，下一次轮询拿到）。"""
        try:
            with open(REQ_F, "w") as f:
                f.write("1\n")
        except OSError:
            pass

    def set_wb(self, wb):
        wb = round(max(WB_MIN, min(WB_MAX, float(wb))) / WB_STEP) * WB_STEP
        self.wb = round(wb, 2)
        self.w_auto = False
        self.dirty = True
        # ✅ 2026-10-20 23:0x 实测终定：`BalanceRatio` 是**正比**语义（比值大 = 该通道亮）。
        #   之前写成"反比"是因为我把原始缓冲当成 BGR 了；
        #   用 "只动一个选择器" 的对照实验确定：Red→idx0、Green→idx1、Blue→idx2，
        #   就是 **RGB 顺序**。所以 +wb 就是加红（偏暖）。
        # ★ 以"AWB 收敛后的基线"为基准做乘性微调 —— 这样自动白平衡的结果不会被
        #   覆盖，手动 + / - 是在它上面继续加暖/加冷。
        g = self.wb_base[1]
        r = max(1.0, self.wb_base[0] * 2.0 ** self.wb)
        b = max(1.0, self.wb_base[2] * 2.0 ** (-self.wb))
        # 冷暖轴：红蓝反向动，绿固定 1.0x —— 一条命令里写完三个通道
        hw_set_many([
            ("BalanceWhiteAuto", "Off"),
            # ★ BalanceRatio 是**整数节点**，必须发整数。发 "2048.0" 时
            #   int("2048.0") 会抛错、整数分支被跳过 ⇒ 整条命令失败（实测 ctlrep=-1）。
            ("BalanceRatioSelector", "Red"), ("BalanceRatio", "%.0f" % r),
            ("BalanceRatioSelector", "Blue"), ("BalanceRatio", "%.0f" % b),
            ("BalanceRatioSelector", "Green"), ("BalanceRatio", "%.0f" % g),
        ])

    def step_cur(self, up):
        if self.mode == "exp":
            self.exp_step(up)
            self.toast_set("曝光 %s ms" % fmt_ms(self.exp_us), 1.2)
        elif self.mode == "gain":
            g = self.hwstat.get("Gain")
            g = 0.0 if g is None else float(g)
            self.set_gain(g + (GAIN_STEP if up else -GAIN_STEP))
            self.toast_set("增益 %.1f dB" % g, 1.2)
        else:
            self.set_wb(self.wb + (WB_STEP if up else -WB_STEP))
            self.toast_set("色温 %+.1f" % self.wb, 1.2)

    def toggle_auto(self):
        if self.mode == "exp":
            self.auto = not self.auto
            self.toast_set("自动曝光 开" if self.auto else "自动曝光 关")
        elif self.mode == "gain":
            self.g_auto = not self.g_auto
            hw_set("GainAuto", "Continuous" if self.g_auto else "Off")
            self.toast_set("自动增益 开" if self.g_auto else "自动增益 关")
        else:
            # ★ 实测（2026-10-20 23:0x）：相机自带的自动白平衡**很好用** ——
            #   开 Continuous 后约 4 s 收敛，R/G/B 均值的 max/min 从 2.52 降到 1.20。
            #   所以不自己写闭环，直接用它：开 4 s、再自动切 Off（即"一次性 AWB"）。
            if self.w_auto:
                hw_set("BalanceWhiteAuto", "Off")
                self.w_auto = False
                self.toast_set("自动色温 关")
            else:
                hw_set("BalanceWhiteAuto", "Continuous")
                self.w_auto = True
                self._awb_until = time.time() + 4.0
                self.toast_set("自动色温 开")
        self.dirty = True

    def reset_cur(self):
        if self.mode == "exp":
            self.auto = False
            if self.hw_ok:
                self.exp_us = EXP_DEFAULT
                self.hw_exp(self.exp_us)
                self.toast_set("曝光复位 %s ms" % fmt_ms(self.exp_us))
            else:
                self.ev = 0.0
                self.toast_set("曝光复位 EV 0.00")
        elif self.mode == "gain":
            self.set_gain(GAIN_DEFAULT)
            self.toast_set("增益复位 %.1f dB" % GAIN_DEFAULT)
        else:
            self.set_wb(0.0)
            self.toast_set("色温复位 0.0")

    def nudge_ev(self, d):
        self.step_cur(d > 0)

    # ---------------------------------------------------------- 动作
    def toast_set(self, s, sec=2.2):
        self.toast = s
        self.toast_until = time.time() + sec
        self.dirty = True

    def tap(self, nm):
        if nm is None:
            return
        if self.a.verbose:
            print("  TAP  %-32s screen=%s ev=%+.2f queue=%d"
                  % (nm, self.screen, self.ev, len(self.queue)), flush=True)
        if nm == "go_gal":
            self.screen = "gal"
            self.chrome_ok = False
            self.regions = []      # ★ 立刻作废旧热区：open_cam() 要 ~1 s，这期间
            self.refresh_photos()  #   真实触摸会拿上一屏的热区去命中（实测踩到过：
            self.close_cam()       #   已经回到拍照屏，按中间却命中了图库的缩略图）
            self.dirty = True
        elif nm == "go_cam":
            self.screen = "cam"
            self.chrome_ok = False
            self.regions = []
            self.open_cam()
            self.dirty = True
        elif nm == "shutter":
            self.shot_pending = True
        elif nm == "sleep_now":
            self.toast_set("手动待机", 1.0)
            self.do_sleep(manual=True)
        elif nm == "sleep_never":
            self.sleep_never = not self.sleep_never
            self.dirty = True
            self.toast_set("已设为**永不待机**" if self.sleep_never else "已恢复自动待机", 2.0)
        elif nm in ("mode_exp", "mode_gain", "mode_wb"):
            self.mode = nm.split("_", 1)[1]
            self.dirty = True
            self.toast_set({"exp": "曝光", "gain": "增益", "wb": "色温"}[self.mode],
                           1.0)
        elif nm == "ev_minus":
            self.step_cur(False)
        elif nm == "ev_plus":
            self.step_cur(True)
        elif nm in ("sz_small", "sz_big"):
            self.img_big = (nm == "sz_big")
            self.dirty = True
            self.toast_set("发送大图 512（4 块 256 拼）" if self.img_big
                           else "发送小图 256", 1.5)
        elif nm == "ev_auto":
            self.toggle_auto()
        elif nm == "ev_reset":
            self.reset_cur()
        elif nm == "send_last":
            # ★ 用 latest（mtime 最大那张），**不是 photos[0]**
            #   列表已按文件名升序 ⇒ photos[0] 是**最旧**的，用它会把"发送最新"变成"发送最旧"。
            if self.latest:
                self.start_send(self.latest)
            else:
                self.toast_set("还没有照片，先按快门")
        elif nm == "page_prev":
            self.turn_page(-1)
        elif nm == "page_next":
            self.turn_page(1)
        elif nm == "send_sel":
            # 发**整个队列**（不是一张）—— 队列空才提示
            if not self.queue:
                self.toast_set("先点缩略图把要发的加进队列")
            else:
                self.start_queue(self.queue)
        elif nm == "clear_q":
            # 二次确认：队列可能是攒了很久选的，误触一下就清空太亏
            if not self.queue:
                self.toast_set("队列本来就是空的")
            elif time.time() < self.clear_until:
                n = len(self.queue)
                self.queue = []
                self.clear_until = 0.0
                self.toast_set("已清空队列（%d 张）" % n)
                self.dirty = True
            else:
                self.clear_until = time.time() + 3.0
                self.toast_set("再点一次「清空」确认（%d 张）" % len(self.queue))
                self.dirty = True
        elif nm == "q_all":
            # 把**本栏当前页**全部加入队列（快速攒一批）
            add = [p for p, _, _ in self.photos[self.gal_page * 8:(self.gal_page + 1) * 8]]
            new = [p for p in add if p not in self.queue]
            self.queue.extend(new)
            self.toast_set("本页新增 %d 张，队列共 %d 张" % (len(new), len(self.queue)))
            self.dirty = True
        elif nm == "reload":
            self.refresh_photos()
            self.toast_set("已重新扫描：相机 %d 张 / 相册 %d 张" % (self.n_cam, self.n_alb))
        elif nm and nm.startswith("gal_tab:"):
            self.set_tab(int(nm[8:]))
        elif nm and nm.startswith("thumb:"):
            # ★ 点缩略图 = 加入/移出**发送队列**（不再是一次只能选一张）
            p = nm[6:]
            if p in self.queue:
                self.queue.remove(p)
                self.toast_set("已移出队列：%s（队列 %d 张）"
                               % (os.path.basename(p), len(self.queue)))
            else:
                self.queue.append(p)
                self.toast_set("已加入队列第 %d 位：%s"
                               % (len(self.queue), os.path.basename(p)))
            self.dirty = True

    def turn_page(self, d):
        npg = max(0, self.gal_page + d)
        if npg != self.gal_page:
            self.gal_page = npg
            self.dirty = True

    def _scan_dir(self, d):
        """扫一个目录里的图片，**按文件名升序**返回 [(path, mtime, size), ...]。

        为什么按名字不按 mtime：用户要的是"按顺序排列"。
        `IMG_0001…0022` 这种编号本身就带顺序；按 mtime 排会变成倒序（最新的在最前），
        而且拷进来的图 mtime 全相同，顺序就随机了（实测踩到过）。
        """
        lst = []
        try:
            for n in os.listdir(d):
                if not n.lower().endswith((".jpg", ".jpeg", ".png", ".bmp")):
                    continue
                p = os.path.join(d, n)
                if not os.path.isfile(p):
                    continue          # 跳过同名目录（album/ 自己就住在这里面）
                try:
                    lst.append((p, os.path.getmtime(p), os.path.getsize(p)))
                except OSError:
                    pass
        except OSError:
            pass
        lst.sort(key=lambda t: os.path.basename(t[0]).lower())
        return lst

    def refresh_photos(self):
        cam = self._scan_dir(PHOTO_DIR)
        alb = self._scan_dir(ALBUM_DIR)
        self.groups = [("cam", "相机", cam), ("alb", "相册", alb)]
        self.n_cam, self.n_alb = len(cam), len(alb)
        if self.gal_tab >= len(self.groups):
            self.gal_tab = 0
        self.photos = self.groups[self.gal_tab][2]
        # ★ 「发送最新」要的是 **mtime 最大**的那张。
        #   升序排列之后 photos[0] 是**最旧**的 —— 直接拿它会把"发送最新"变成"发送最旧"。
        every = cam + alb
        self.latest = max(every, key=lambda t: t[1])[0] if every else None
        npg = max(1, (len(self.photos) + 7) // 8)
        self.gal_page = min(self.gal_page, npg - 1)
        if self.gal_sel and self.gal_sel not in [p for p, _, _ in every]:
            self.gal_sel = None
        # 队列里若混进了已被删掉的文件，剔掉（否则发到那一步才报错，白等一轮）
        exist = set(p for p, _, _ in every)
        self.queue = [p for p in self.queue if p in exist]
        self.thumbs = {}
        self.dirty = True

    def set_tab(self, k):
        """切「相机 / 相册」。选中项**保留**（可以先在相机里选一张，再去相册选一张发送）。"""
        if not self.groups or k >= len(self.groups) or k == self.gal_tab:
            return
        self.gal_tab = k
        self.photos = self.groups[k][2]
        self.gal_page = 0
        self.dirty = True

    def do_shot(self):
        import cv2
        f = self.last_frame
        if f is None:
            self.toast_set("没有可用帧")
            return
        os.makedirs(PHOTO_DIR, exist_ok=True)
        # ★ 编号必须在**相机组**里找最大值。self.photos 可能是「相册」那一组
        #   （用户上次停在相册页），拿它算会让快门编号与相机组重名 —— **直接覆盖已有照片**。
        cam = self.groups[0][2] if self.groups else self._scan_dir(PHOTO_DIR)
        mx = 0
        for p, _, _ in cam:
            b = os.path.basename(p)
            if b.startswith("IMG_") and len(b) > 8 and b[4:8].isdigit():
                mx = max(mx, int(b[4:8]))
        name = "IMG_%04d.jpg" % (mx + 1)
        path = os.path.join(PHOTO_DIR, name)
        t0 = time.time()
        ok = cv2.imwrite(path, f, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        sz = os.path.getsize(path) if ok and os.path.exists(path) else 0
        self.n_shot += 1
        self.flash_until = time.time() + 0.16
        if ok and sz:
            self.toast_set("已保存 %s  (%.1f KB, EV %+.2f, %.0f ms)"
                           % (name, sz / 1024.0, self.ev, (time.time() - t0) * 1000), 3.0)
        else:
            self.toast_set("保存失败 %s" % name)
        self.refresh_photos()

    # ---------------------------------------------------------- 发送（队列）
    def start_send(self, path):
        """单张入口（保留兼容）。实际走队列，只是队列里就一张。"""
        self.start_queue([path])

    def start_queue(self, paths):
        r"""★ 发送队列：**顺序**逐张发，一张发完自动发下一张。

        为什么在 UI 侧排队、而不是把多张塞给 ui_send.sh 一次发：
          · `ui_send.sh` 是单张接口，里面有一套调过的自愈逻辑（电台透传态缓存、
            BEGIN 重试计数、ctime 失效）—— 改成批量要动那套逻辑，风险大收益小。
          · 队列放 UI 侧：每张的 rc / 阶段都能显示，失败能**停在当场**，
            剩下的留在队列里可以重试；也能中途看到发到第几张。
          · 性能上不亏：ui_send.sh 的电台自检只在第一次做（之后命中缓存），
            编码走常驻引擎 —— 实测第二张起每张 ~1.6~3 s。
        """
        if self.send_proc is not None and self.send_proc.poll() is None:
            self.toast_set("上一次发送还没结束")
            return
        paths = [p for p in paths if os.path.isfile(p)]
        if not paths:
            self.toast_set("队列是空的")
            return
        self.send_q = list(paths)
        self.send_i = 0
        self.send_ok = 0
        self.send_bad = []
        self.send_skip = []
        self._send_next()

    def _send_next(self):
        """起队列里第 send_i 张。"""
        if self.send_i >= len(self.send_q):
            self._queue_done()
            return
        path = self.send_q[self.send_i]
        env = dict(os.environ)
        # 电台有无由 ui_send.sh 自己判断：有电台 -> AT自检与编码并行 + 真发；
        # 没电台 -> 只编码并明确报告"未发射"。这里不再强行指定。
        env.pop("GLC_ALLOW_NO_RADIO", None)
        # 大图/小图：ui_send.sh 据此决定"512 切 4 块、N=4 会话 MODE=1"还是"中心裁 256、N=1 MODE=0"
        env["GLC_UI_BIG"] = "1" if self.img_big else "0"
        try:
            lf = open(SEND_LOG, "wb")
        except OSError as e:
            self.toast_set("打不开日志 %s" % e)
            return
        self.send_logf = lf
        self.send_proc = subprocess.Popen(["bash", SEND_SH, path], cwd="/root",
                                          stdin=subprocess.DEVNULL,
                                          stdout=lf, stderr=subprocess.STDOUT, env=env)
        self.send_t0 = time.time()
        self.send_path = path
        self.send_state = "run"
        self.send_msg = ("发送中 第 %d/%d 张 …" % (self.send_i + 1, len(self.send_q))
                         if len(self.send_q) > 1 else "发送中…")
        self.dirty = True

    def _dims(self, path):
        """图片宽高（带缓存）。取不到就返回 (0,0)，界面显示 0×0 而不是崩。"""
        try:
            mt = os.path.getmtime(path)
        except OSError:
            return (0, 0)
        cache = getattr(self, "_dim_cache", None)
        if cache is None:
            cache = self._dim_cache = {}
        key = (path, mt)
        if key in cache:
            return cache[key]
        wh = (0, 0)
        try:
            from PIL import Image as _I
            with _I.open(path) as im:
                wh = im.size
        except Exception:
            pass
        cache[key] = wh
        return wh

    def _queue_done(self):
        """队列收尾。失败时**剩下的留在 self.queue 里**，可以直接再点一次重试。"""
        n_all = len(self.send_q)
        left = n_all - self.send_i
        hard_fail = [b for b in self.send_bad if b[1] != 12]
        if hard_fail:
            _, rc, why = hard_fail[-1]
            self.send_state = "fail"
            self.send_msg = ("队列 %d 张：成功 %d，第 %d 张失败 rc=%d %s；剩 %d 张留在队列"
                             % (n_all, self.send_ok, self.send_i + 1, rc, why, left))
            # ★ 失败那张 + 它后面的都留着 —— 一键重试，不用重新一张张点
            self.queue = list(self.send_q[self.send_i:])
        elif self.send_skip:
            # 只有"产物损坏被跳过"这种情况：整条队列已经走完，如实汇报第几张
            self.send_state = "ok"
            bad = "、".join(str(k) for k in self.send_skip)
            self.send_msg = ("队列 %d 张：发出 %d，跳过 %d（第 %s 张产物损坏）"
                             % (n_all, self.send_ok, len(self.send_skip), bad))
            self.queue = []
        else:
            self.send_state = "ok"
            self.send_msg = "队列 %d 张全部发出（成功 %d）" % (n_all, self.send_ok)
            self.queue = []
        self.send_q, self.send_i, self.send_ok, self.send_bad, self.send_skip = [], 0, 0, [], []
        self.refresh_photos()
        self.dirty = True

    def poll_send(self):
        if self.send_proc is None:
            return
        rc = self.send_proc.poll()
        if rc is None:
            # 编码一次要 ~8 s，得让用户看见在动，并且看见在哪个阶段
            el = time.time() - self.send_t0
            s = int(el)
            if not hasattr(self, "_send_s") or self._send_s != s:
                self._send_s = s
                stage = "准备"
                try:
                    head = open(SEND_LOG, "rb").read().decode("utf-8", "replace")
                    # ui_send.sh 只发 **ASCII 状态码**（STAGE=ENC 之类），中文文案留在下面这张表里。
                    # ★ 为什么不让脚本直接发中文：字体覆盖率自检只扫**本文件的字符串字面量**，
                    #   脚本文本是运行期从日志读进来的，自检根本看不见 —— 中文放脚本里迟早
                    #   又出一个"绪/驻"的豆腐块。放这张表里就自动被自检管住了。
                    for ln in head.splitlines():
                        if ln.startswith("[UI] STAGE="):
                            stage = STAGE_TEXT.get(ln[11:].strip(), stage)
                    # 等对方 ACK 是最熬人的一段：BEGIN 默认最多试 N 次 × (等6s+隔4s)。
                    # 不把进度显示出来，用户在屏前就是干等，会以为死机了。
                    if stage == STAGE_TEXT["SEND"]:
                        last_b = ""
                        for ln in head.splitlines():
                            if "SESSION_BEGIN 第" in ln:
                                last_b = ln.strip()
                        if last_b:
                            k = last_b.split("第")[1].split("次")[0].strip()
                            stage = "等对方应答 BEGIN %s" % k
                        elif "SESSION_BEGIN 已确认" in head:
                            i = head.rfind("进度：已发")
                            stage = head[i:i + 24].strip() if i >= 0 else "对方已收，传数据中"
                except OSError:
                    pass
                self.send_msg = "发送中 %.0fs · %s" % (el, stage)
                self.dirty = True
            return
        try:
            self.send_logf.close()
        except Exception:
            pass
        el = time.time() - self.send_t0
        tail = ""
        try:
            tail = open(SEND_LOG, "rb").read().decode("utf-8", "replace")
        except OSError:
            pass

        # ui_send.sh 最后一行固定输出 UI_SEND_DONE rc=N stage=... radio=0/1
        stage, radio, n_sent = "", 1, 0
        for ln in tail.splitlines():
            if ln.startswith("UI_SEND_DONE"):
                for kv in ln.split()[1:]:
                    if "=" in kv:
                        k, v = kv.split("=", 1)
                        if k == "stage":
                            stage = v
                        elif k == "radio" and v.isdigit():
                            radio = int(v)
                        elif k == "n" and v.isdigit():
                            n_sent = int(v)
        glc = ""
        for ln in tail.splitlines():
            if ln.strip().startswith("=> ") and ".glc" in ln:
                glc = ln.strip()
        self.glc_line = glc

        ok = False
        why = ""
        if rc == 0 and stage == "encode_only":
            self.send_state = "ok"
            self.send_msg = "已编码(GLC) %.0fs — 无电台未发射" % el
            ok = True
        elif rc == 0 and n_sent:
            self.send_state = "ok"
            self.send_msg = "发送完成 %.0fs（已空口发出）" % el
            ok = True
        else:
            self.send_state = "fail"
            # ★ 2026-10-23：rc=12 是 ui_send.sh 新增的"容器过大"拒发（见 ui_send.sh ③.5）。
            #   正常画面容器 300~400 B，超 1200 B 基本就是噪声/坏帧；
            #   硬发会因为超过单帧上限（实测 1280 B）一直等不到 ACK，白等 80~237 s。
            why = {"at": "电台自检没过", "encode": "编码失败",
                   "container": "没找到容器", "size": "画面异常(容器过大)，请重拍",
                   "send": "对方未确认"}.get(stage, "")
            last = [l for l in tail.strip().splitlines() if l.strip()][-2:-1] or [""]
            if rc == 12:
                # ★ 2026-10-23 用户定：产物损坏 ⇒ 已重编过一次仍坏 ⇒ **跳过这张、继续发下一张**，
                #   最后统一汇报"第几张损坏"。不再让整条队列停在坏帧上。
                self.send_msg = ("第 %d/%d 张产物损坏（重编后仍 >1200 B），已跳过"
                                 % (self.send_i + 1, len(self.send_q)))
            else:
                self.send_msg = "失败 rc=%d %s %.0fs | %s" % (rc, why, el, last[0][:60])
        self.send_proc = None

        # ---- 队列推进（2026-10-15）------------------------------------------
        #   成功 -> 记一笔并前进；失败 -> **send_i 不动**、队列停在这里，
        #   剩下的（含失败那张）由 _queue_done() 放回 self.queue，可一键重试。
        #   为什么失败就停：N 张发不出去的常见原因（电台没了 / 对方没在听 / 自检没过）
        #   对后面每一张同样成立，硬发下去就是白等 N × 30 s。
        skipped = (rc == 12)          # 产物损坏：跳过这张，继续下一张
        if ok:
            self.send_ok += 1
            self.send_i += 1
        elif skipped:
            self.send_bad.append((self.send_path, rc, u'产物损坏'))
            self.send_skip.append(self.send_i + 1)      # 1 基序号
            self.send_i += 1
        else:
            self.send_bad.append((self.send_path, rc, why))
        if (ok or skipped) and self.send_i < len(self.send_q):
            self._send_next()
        else:
            self._queue_done()
        self.dirty = True

    # ---------------------------------------------------------- 渲染
    def render(self):
        cv = self.canvas
        if self.screen == "cam":
            self.render_cam(cv)
        else:
            self.render_gal(cv)

    def blit_preview(self, cv):
        r"""把最新一帧等比贴进预览区（1024x458 的中间）。

        ★★ 插值一定用 INTER_LINEAR，**不要用 INTER_AREA**。
           实测（2026-10-15 分段计时）：换掉 INTER_AREA 省了 12 ms/帧。
           这里缩放比只有 0.954x（640x480 -> 610x458，几乎 1:1），
           INTER_AREA 那套"多像素加权平均"的优势在这个比例下完全用不上，纯属白付代价；
           INTER_LINEAR 有定点 SIMD 快路径，这个比例下肉眼无差别。
        ★ 预览矩形 (207..817, 46..504) 与左右面板(10..162 / 830..1014)、上下栏都**不重叠**，
          所以单独贴它是安全的 —— 这也是 render_preview_only 能成立的前提。
        """
        import cv2
        if self.last_frame is None:
            self.prev_rect = None
            return
        f = self.last_frame
        fh, fw = f.shape[:2]
        s = min(645.0 / fw, (PY1 - PY0) / float(fh))
        nw, nh = max(1, int(fw * s)), max(1, int(fh * s))
        r = cv2.resize(f, (nw, nh), interpolation=cv2.INTER_LINEAR)
        x0, y0 = (W - nw) // 2, PY0 + (PY1 - PY0 - nh) // 2
        cv[y0:y0 + nh, x0:x0 + nw] = r
        self.prev_rect = (x0, y0, x0 + nw, y0 + nh)

    def render_preview_only(self):
        r"""稳态下的快路径：**只贴预览，不重画界面**。

        为什么需要：原来每来一帧就把整个界面重画一遍（顶栏/面板/按钮/底栏/二十几条文字），
        实测 render 要 125~155 ms，屏上只有 6~7 fps —— 而相机明明能给 12.5 fps。
        但稳态下真正在变的**只有预览那 610x458**，左右面板和上下栏一个像素都没动。
        所以：界面状态变了(``dirty``)才走整画，新帧来了只贴预览。
        """
        if self.last_frame is None:
            return
        self.blit_preview(self.canvas)

    def render_cam(self, cv):
        import cv2
        self.regions = []
        cv[:] = PAL["bg"]
        self.canvas[PY0:PY1, :] = PAL["black"]

        # --- 顶栏
        cv[0:TOP_H, :] = PAL["bar"]
        txt(cv, "GLC 拍照", 16, TOP_H // 2 + 1, 26, PAL["txt"], "lm")
        n = self.n_cam                     # 「已拍」= 相机那组（快门拍的），不含相册导入的
        tb = self.top_buttons(cv)                      # 手动待机 / 永不待机
        txt(cv, "已拍 %d 张" % n, tb["text_right"], TOP_H // 2 + 1, 20, PAL["dim"], "rm")

        # --- 预览（等比放进 1024x458，两侧留黑给左右面板）
        self.blit_preview(cv)
        if self.last_frame is None:
            txt(cv, "无信号 / 相机未打开", W // 2, (PY0 + PY1) // 2, 28, PAL["dim"], "cm")

        # --- 左控制面板：曝光 / 增益 / 白平衡 三选一
        x0, y0, x1, y1 = PANEL
        cv[y0:y1, x0:x1] = PAL["bar2"]      # 预览 610 宽居中(207..817)，永远不会压到这
        rrect(cv, PANEL, PAL["bar"], r=12, fill=False, thick=2)

        # 三个模式按钮（点谁调谁）
        mb_y0, mb_y1 = y0 + 8, y0 + 40
        mw = (x1 - x0 - 16 - 8) // 3
        for k, (mk, ml) in enumerate((("exp", "曝光"), ("gain", "增益"), ("wb", "色温"))):
            bx0 = x0 + 8 + k * (mw + 4)
            bb = (bx0, mb_y0, bx0 + mw, mb_y1)
            button(cv, bb, ml, 14, PAL["ok"] if self.mode == mk else PAL["btn"])
            self.regions.append(("mode_" + mk,) + bb)

        val, note = self.cur_mode_text()
        txt(cv, note, (x0 + x1) // 2, y0 + 58, 14, PAL["dim2"], "ct")
        txt(cv, val, (x0 + x1) // 2, y0 + 100, 32,
            PAL["accent"] if self.cur_auto() else PAL["txt"], "cm")

        # 竖向滑块（位置由当前模式决定）
        tx0, tx1 = (x0 + x1) // 2 - 15, (x0 + x1) // 2 + 15
        ty0, ty1 = y0 + 136, y1 - 122
        rrect(cv, (tx0, ty0, tx1, ty1), PAL["dis"], r=15, fill=True)
        f = self.cur_frac()
        ky = int(ty1 - f * (ty1 - ty0))
        # ★ 原来写的是 `if 0.0 < f < 1.0:` —— 到顶（f 正好 = 1.0，例如 60 ms 那一格）
        #   条件不成立，蓝条整条不画，看起来像"滑块坏了"。改成只要 f > 0 就画，
        #   并把上边界夹进轨道内（f=1 时 ky == ty0，正好画满全程）。
        if f > 1e-3:
            cv[max(ky, ty0):ty1, tx0 + 3:tx1 - 3] = PAL["hi"]
        for e in range(5):
            yy = int(ty1 - e / 4.0 * (ty1 - ty0))
            cv[yy:yy + 2, tx0 - 6:tx0 - 1] = PAL["dim2"]
        cv2.circle(cv, ((tx0 + tx1) // 2, ky), 15, PAL["white"], -1)
        cv2.circle(cv, ((tx0 + tx1) // 2, ky), 15, PAL["hi"], 3)
        self.regions.append(("slider_ev", tx0 - 24, ty0 - 16, tx1 + 24, ty1 + 16))

        # ★ - 和 + 放到竖滑条**两侧**，做成竖长条（用户 2026-10-20 要求：更好按）。
        #   原来在滑条下面各占一半宽、只有 40px 高，拇指容易点空。
        mb0, mb1 = ty0 + 24, ty1 - 24
        lm = (x0 + 8, mb0, tx0 - 14, mb1)
        rp = (tx1 + 14, mb0, x1 - 8, mb1)
        button(cv, lm, "-", 34)
        button(cv, rp, "+", 34)
        self.regions.append(("ev_minus",) + lm)
        self.regions.append(("ev_plus",) + rp)
        bw = (x1 - x0) - 24
        # ★ 2026-10-23：把 AUTO/复位 上移 42 px，腾出最底下一整行放「发送尺寸」开关。
        #   滑块下沿是 y1-122，AUTO 行顶 y1-92 ⇒ 仍不重叠。
        ab = (x0 + 12, y1 - 92, x0 + 12 + bw * 60 // 100, y1 - 54)
        rb = (ab[2] + 8, y1 - 92, x1 - 12, y1 - 54)
        button(cv, ab, "AUTO", 19, PAL["ok"] if self.cur_auto() else PAL["btn"])
        button(cv, rb, "复位", 19)
        self.regions.append(("ev_auto",) + ab)
        self.regions.append(("ev_reset",) + rb)


        # --- 右侧信息栏
        ix0, ix1 = INFOX
        iy = PY0 + 14
        exp_v = self.hwstat.get("ExposureTime")
        gain_v = self.hwstat.get("Gain")
        over = self.clip > CLIP_TARGET
        # ★ 必须报**实际**帧尺寸：self.a.cw/ch 是命令行请求值（默认 640x480），
        #   实测板上原来一直显示 640x480，而真实帧是 256x256（grab.real_wh）。
        rw, rh = getattr(self.grab, "real_wh", (0, 0)) or (0, 0)
        if not rw:
            rw, rh = self.a.cw, self.a.ch
        # ★ 记下"已经画出去的分辨率"，主循环一旦发现真值变了就整画一次。
        #   不加这个的话：开机首帧还没到 ⇒ real_wh=(0,0) ⇒ 退回命令行默认 640x480，
        #   之后相机真值变成 256x256 也**没人触发重画**，屏上就一直挂着 640x480
        #   （用户 2026-10-20 实测发现）。
        self.wh_shown = (rw, rh)
        lines = [
            ("相机", "%dx%d RGB8" % (rw, rh), PAL["txt"]),
            ("帧率", "%.1f fps" % self.fps, PAL["txt"]),
            ("曝光", (fmt_ms(exp_v) + " ms") if exp_v is not None else "-- ms",
             PAL["accent"] if self.auto else PAL["txt"]),
            ("增益", ("%.1f dB" % gain_v) if gain_v is not None else "-- dB",
             PAL["txt"]),
            # ★ 用户 2026-10-20 要求：这一行从"高光"换成白平衡。
            #   标签用"色温"而不是"白平衡"——字体子集里没有"衡"字(U+8861)，
            #   写"白平衡"会渲染成 "白平?"；左边那个模式按钮也叫"色温"，保持一致。
            ("色温", ("%+.1f" % self.wb) + (" AUTO" if self.w_auto else ""),
             PAL["accent"] if self.w_auto else PAL["txt"]),
            ("电台", "有" if os.path.exists(RADIO) else "无", PAL["txt"]),
            ("已拍", "%d 张" % self.n_cam, PAL["txt"]),
            ("相册", "%d 张" % self.n_alb, PAL["txt"]),
        ]
        for k, v, *c in lines:
            txt(cv, k, ix0, iy, 17, PAL["dim2"], "lt")
            txt(cv, v, ix0, iy + 20, 19, (c[0] if c else PAL["txt"]), "lt")
            iy += 48
        txt(cv, self.err or "", ix0, PY1 - 16, 15, PAL["bad"], "lb")

        # --- 底栏
        cv[H - BOT_H:H, :] = PAL["bar"]
        b1 = (20, 514, 190, 574)
        button(cv, b1, "图库", 26)
        self.regions.append(("go_gal",) + b1)
        b2 = (834, 514, 1004, 574)
        button(cv, b2, "发送最新", 22,
               PAL["hi"] if n else PAL["dis"])
        self.regions.append(("send_last",) + b2)

        cx, cy, r = 512, 546, 40
        cv2.circle(cv, (cx, cy), r, PAL["white"], -1)
        cv2.circle(cv, (cx, cy), r - 6, PAL["bad"], -1)
        cv2.circle(cv, (cx, cy), r - 9, BGR(228, 60, 52), -1)
        txt(cv, "快门", cx, cy, 22, PAL["white"], "cm")
        self.regions.append(("shutter", cx - r - 10, cy - r - 8, cx + r + 10, cy + r + 8))

        # --- 状态行：拆成左右两块，**中间那块是快门圆，谁都不许压过去**
        #   快门圆心 (512,546) r=40 ⇒ 占 x 472~552、y 506~586。
        #   状态行在 y≈576~598，所以文字必须止于 x≈466，或者从 x≈558 才开始。
        #   原来是从 x=210 一路往右画 —— 长一点就压在快门上了（用户实测发现）。
        #   左块：静态操作提示（短，固定）；右块：发送状态 / toast（长，动态）
        col = {"idle": PAL["dim"], "run": PAL["accent"], "ok": PAL["ok"],
               "fail": PAL["bad"]}[self.send_state]
        fit_txt(cv, "左下角进图库 · 中间红圈快门", 205, 578, 258, 18, PAL["dim2"], "lt")
        if time.time() < self.toast_until:
            fit_txt(cv, self.toast, 1008, 578, 444, 17, PAL["accent"], "rt")
        elif self.send_state != "idle":
            fit_txt(cv, self.send_msg, 1008, 578, 444, 17, col, "rt")

        if time.time() < self.flash_until:
            cv[PY0:PY1, :] = 255
        if self.a.show_touch:
            self.draw_touch(cv)

    def thumb(self, path, size):
        import cv2
        from PIL import Image
        bw, bh = size
        key = (path, bw, bh)
        t = self.thumbs.get(key)
        if t is None:
            try:
                mt = os.path.getmtime(path)
            except OSError:
                return None
            im = Image.open(path).convert("RGB")
            im.thumbnail((bw, bh), Image.BILINEAR)
            a = np.asarray(im)[:, :, ::-1].copy()      # RGB -> BGR（画布是 BGR）
            t = (mt, a)
            self.thumbs[key] = t
        return t[1]

    def render_gal(self, cv):
        import cv2
        self.regions = []
        cv[:] = PAL["bg"]
        cv[0:TOP_H, :] = PAL["bar"]
        txt(cv, "GLC 图库", 16, TOP_H // 2 + 1, 26, PAL["txt"], "lm")
        n = len(self.photos)
        npg = max(1, (n + 7) // 8)
        tb = self.top_buttons(cv, with_back=True)      # 返回拍照 / 永不待机 / 手动待机
        txt(cv, "第 %d/%d 页" % (self.gal_page + 1, npg),
            tb["text_right"], TOP_H // 2 + 1, 19, PAL["dim"], "rm")

        # --- 「相机 / 相册」分栏（2026-10-15）---------------------------------
        #   相机 = /root/photos/ 根下（快门拍的）；相册 = /root/photos/album/（导入的）。
        #   各自**按文件名升序**排（refresh_photos 里排好），不是按时间倒序。
        tby0, tby1 = 50, 88
        gx_ = (W - (4 * 236 + 3 * 14)) // 2
        bxx = gx_
        for i, (key, label, lst) in enumerate(self.groups):
            bw_ = 170
            b = (bxx, tby0, bxx + bw_, tby1)
            bxx = b[2] + 10
            on = (i == self.gal_tab)
            button(cv, b, "%s %d 张" % (label, len(lst)), 18,
                   PAL["hi"] if on else PAL["btn"],
                   PAL["txt"] if on else PAL["dim"])
            if on:      # 选中的那栏加个下划线，一眼看出在哪一栏
                cv[tby1 + 2:tby1 + 5, b[0] + 8:b[2] - 8] = PAL["hi"]
            self.regions.append(("gal_tab:%d" % i,) + b)

        # 「重新扫描」按钮 —— tap 里的 reload 分支一直存在，但**从来没人注册过它的热区**
        # （等于死代码）。2026-10-15 补上，顺手也把相册那栏的提示文案落到实处。
        rb = (400, tby0, 560, tby1)
        button(cv, rb, "重新扫描", 18)
        self.regions.append(("reload",) + rb)

        # 「全选本页」+「清空队列」—— 队列操作放这一行，底栏留给翻页与发送
        qb = (580, tby0, 720, tby1)
        button(cv, qb, "全选本页", 18)
        self.regions.append(("q_all",) + qb)
        nq = len(self.queue)
        chb = (730, tby0, 880, tby1)
        pending = time.time() < self.clear_until
        # 平时是普通灰底（它只是"清空"，不是错误）；**只有进了二次确认窗口才变红**。
        # 一直红着会被当成"出错了"，反而让人不敢按。
        button(cv, chb, "确认清空" if pending else "清空队列", 18,
               PAL["bad"] if pending else PAL["btn"],
               PAL["white"] if pending else PAL["txt"])
        self.regions.append(("clear_q",) + chb)

        if n == 0:
            empty = ("还没有照片" if self.gal_tab == 0 else "相册是空的")
            hint = ("回到拍照界面按中间的红色快门"
                    if self.gal_tab == 0 else
                    "把图拷进 /root/photos/album/ 后，点上面的「重新扫描」")
            txt(cv, empty, W // 2, 260, 34, PAL["dim"], "cm")
            txt(cv, hint, W // 2, 306, 22, PAL["dim2"], "cm")
        else:
            cw_, ch_ = 236, 196          # 比原来矮 14 px，给上面的分栏腾地方
            gx, gy = 14, 14
            mx = (W - (4 * cw_ + 3 * gx)) // 2
            my = 96
            for i in range(8):
                k = self.gal_page * 8 + i
                if k >= n:
                    break
                path, mt, sz = self.photos[k]
                c = i % 4
                r_ = i // 4
                bx0 = mx + c * (cw_ + gx)
                by0 = my + r_ * (ch_ + gy)
                box = (bx0, by0, bx0 + cw_, by0 + ch_)
                qn = (self.queue.index(path) + 1) if path in self.queue else 0
                sel = (qn > 0)
                rrect(cv, box, PAL["hi"] if sel else PAL["bar"], r=12, fill=True)
                ib = (bx0 + 6, by0 + 6, bx0 + cw_ - 6, by0 + 6 + 136)
                cv[ib[1]:ib[3], ib[0]:ib[2]] = PAL["black"]
                th = self.thumb(path, (ib[2] - ib[0], ib[3] - ib[1]))
                if th is not None:
                    h_, w_ = th.shape[:2]
                    ox = ib[0] + (ib[2] - ib[0] - w_) // 2
                    oy = ib[1] + (ib[3] - ib[1] - h_) // 2
                    cv[oy:oy + h_, ox:ox + w_] = th
                nm = os.path.basename(path)
                txt(cv, nm if len(nm) <= 17 else nm[:14] + "…", bx0 + 10, by0 + 148, 17,
                    PAL["txt"] if sel else PAL["dim"], "lt")
                # ★ 2026-10-23 用户要求：图库缩略图要显示**图片大小**，并且要能看出
                #   这张是 256×256 还是 512×512（压缩比的分母就是这个尺寸的 JPEG 字节数）。
                #   尺寸带缓存（按 路径+mtime），翻页/重绘不会反复解码。
                wh = self._dims(path)
                txt(cv, "%d×%d  %.1f KB" % (wh[0], wh[1], sz / 1024.0),
                    bx0 + 10, by0 + 170, 15,
                    PAL["txt"] if sel else PAL["dim2"], "lt")
                txt(cv, time.strftime("%m-%d %H:%M", time.localtime(mt)),
                    bx0 + 10, by0 + 190, 13,
                    PAL["txt"] if sel else PAL["dim2"], "lt")
                if sel:
                    # ★ 徽章画的是**队列序号**（不是个勾）—— 一眼看出"第几个发"，
                    #   这正是"形成发送队列"要表达的东西。
                    cv2.circle(cv, (bx0 + cw_ - 24, by0 + 24), 16, PAL["ok"], -1)
                    txt(cv, str(qn), bx0 + cw_ - 24, by0 + 24, 19, PAL["white"], "cm")
                self.regions.append(("thumb:" + path,) + box)

        cv[H - BOT_H:H, :] = PAL["bar"]
        # ★ 2026-10-23 用户要求：从左到右 上一页·下一页·256·512·发送队列；
        #   原来 下一页(196..356) 与 小图(296..402) 重叠 ⇒ 翻页键压窄并左移。
        for nm, bx, lb, en in (("page_prev", (14, 520, 124, 584), "上一页", self.gal_page > 0),
                               ("page_next", (132, 520, 242, 584), "下一页",
                                self.gal_page < npg - 1)):
            button(cv, bx, lb, 22, PAL["btn"] if en else PAL["dis"],
                   PAL["txt"] if en else PAL["dim2"])
            self.regions.append((nm,) + bx)
        nq = len(self.queue)
        # ★ 2026-10-23：发送尺寸挪到图库（用户要求"在图库的发图模式里先选大小图再发送"）。
        #   两个按钮做成互斥样式：选中的那个绿底，另一个灰底。
        for nm, bx, lb, on in (("sz_small", (254, 520, 336, 584), "256", not self.img_big),
                               ("sz_big", (344, 520, 426, 584), "512", self.img_big)):
            button(cv, bx, lb, 22, PAL["ok"] if on else PAL["btn"],
                   PAL["txt"] if on else PAL["dim2"])
            self.regions.append((nm,) + bx)
        sb = (438, 520, 700, 584)
        button(cv, sb, "发送队列 (%d)" % nq if nq else "发送队列", 21,
               PAL["hi"] if nq else PAL["dis"],
               PAL["txt"] if nq else PAL["dim2"])
        self.regions.append(("send_sel",) + sb)

        col = {"idle": PAL["dim"], "run": PAL["accent"], "ok": PAL["ok"], "fail": PAL["bad"]}[
            self.send_state]
        # 图库这块右边贴到 x=1008，可用宽度 328；超了自动缩字号/截断，别让它跑出屏
        idle_hint = ("点缩略图加入队列（可跨相机/相册混选），再按「发送队列」"
                     if not nq else "队列 %d 张，按「发送队列」开始" % nq)
        fit_txt(cv, self.send_state == "idle" and idle_hint or self.send_msg,
                712, 524, 300, 17, col, "lt")
        if nq:
            # 队列内容预览：按**发送顺序**列出，太长就截断
            names = [os.path.basename(p) for p in self.queue]
            short = names[:3]
            more = "" if len(names) <= 3 else " → …(+%d)" % (len(names) - 3)
            fit_txt(cv, "顺序: " + " → ".join(short) + more, 712, 552, 300, 16,
                    PAL["txt"], "lt")
        gl = getattr(self, "glc_line", "")
        if gl:
            fit_txt(cv, gl, 712, 578, 300, 15, PAL["dim2"], "lt")
        if time.time() < self.toast_until:
            fit_txt(cv, self.toast, 680, 598, 328, 16, PAL["accent"], "lb")
        if self.a.show_touch:
            self.draw_touch(cv)

    # ---------------------------------------------------------- 休眠 / 唤醒
    def do_sleep(self, manual=False):
        r"""无操作到点：关摄像头 + 熄屏。

        分两步是有意的：
          ① 先把帧缓冲整个涂黑并推下去 —— **这一步之后屏就已经是黑的了**，
             而且显示器不会丢同步（不会弹 "No Signal"）；
          ② 再关显示输出（0x18=0）—— 这才是真正的熄屏省电，TMDS 停，显示器自己进待机。
        顺序反过来的话，万一 ② 之后 ① 没生效，用户会看到一块亮着的旧画面。
        """
        if not self.awake:
            return
        self.awake = False
        self.n_sleep += 1
        self.sleep_t = time.time()
        idle = time.time() - self.last_act
        who = "手动按下「手动待机」" if manual else "无操作 %.0f s" % idle
        self.close_cam()
        # ★ 待机画面：黑底 + 一行灰字。
        #   默认 --sleep-blackout 0 ⇒ **画完就立刻关显示输出**（真熄屏 0x40080018=0），
        #   所以正常情况下那行提示只在"黑屏到断电"这一瞬间闪一下，基本看不见 ——
        #   这是有意的：屏全黑最省电，也最不干扰。触摸照样能唤醒。
        #   想让提示停留一会儿：--sleep-blackout 60；想让它一直可见：--sleep-keep-sync。
        self.draw_standby(None)
        bo = self.a.sleep_blackout
        if self.a.sleep_keep_sync:
            print("  [休眠] %s ⇒ 关摄像头 + 黑屏提示（第 %d 次）；"
                  "--sleep-keep-sync，显示输出永不关（提示一直可见）。触摸唤醒。"
                  % (who, self.n_sleep), flush=True)
        elif bo <= 0:
            self.disp_enable(False)          # 立即关显示输出（真熄屏）
            self.disp_on = False
            print("  [休眠] %s ⇒ 关摄像头 + 立即关显示输出（第 %d 次，真熄屏）。"
                  "触摸屏幕唤醒。" % (who, self.n_sleep), flush=True)
        else:
            # ★ 倒计时模式：屏上显示「待机中，N 秒后将关闭显示」，每秒刷新，
            #   数到 0 再关显示输出。这样提示有用（告诉人还要多久黑屏），又不牺牲省电。
            self.blackout_at = time.time() + bo
            self.count_shown = int(bo + 0.999)
            self.draw_standby(self.count_shown)
            print("  [休眠] %s ⇒ 关摄像头 + 屏上倒计时 %d s（第 %d 次），"
                  "数到 0 就关显示输出。触摸随时唤醒。"
                  % (who, self.count_shown, self.n_sleep), flush=True)

    def top_buttons(self, cv, with_back=False):
        r"""顶栏右上角那排**常驻按钮**：手动待机 / 永不待机（图库再加个返回拍照）。

        拍照和图库两个界面都调用它 ⇒ 两个模式下都能用。
        返回各按钮矩形给调用方排右边的文字用。
        """
        # ★ 2026-10-23 用户要求：这一栏 y 增大一点、按键更高，便于点按
        y0, y1 = 12, TOP_H - 4
        x = W - 8
        boxes = {}
        if with_back:
            b = (x - 96, y0, x, y1)
            x = b[0] - 8
            button(cv, b, "返回拍照", 17)
            self.regions.append(("go_cam",) + b)
        b = (x - 88, y0, x, y1)
        x = b[0] - 8
        # 绿底 = 该模式正生效（和曝光面板的 AUTO 按钮同一个约定）
        button(cv, b, "永不待机", 17, PAL["ok"] if self.sleep_never else PAL["btn"])
        self.regions.append(("sleep_never",) + b)
        b = (x - 88, y0, x, y1)
        x = b[0] - 8
        button(cv, b, "手动待机", 17)
        self.regions.append(("sleep_now",) + b)
        boxes["text_right"] = x - 4
        return boxes

    def draw_standby(self, remain=None):
        """待机画面：黑底 + 一行灰字。

        remain=None -> 「待机中，轻触屏幕唤醒」（不打算关屏时用）
        remain=N    -> 「待机中，N 秒后将关闭显示」（倒计时，每秒重画一次）
        """
        with self.lock:
            self.canvas[:] = 0
            if not self.a.no_sleep_hint:
                s = SLEEP_HINT if remain is None else (SLEEP_COUNTDOWN % remain)
                txt(self.canvas, s, W // 2, H // 2, 30, PAL["gray"], "cm")
            self.regions = []
            self.prev_rect = None
            self.conv_rect(0, 0, W, H)
            self.chunk.write(0, self.u16.tobytes(), BUF)

    def do_wake(self):
        self.awake = True
        self.swallow = True          # 唤醒手势剩下的 move/up 也一并吃掉
        self.last_act = time.time()
        if not self.disp_on:
            self.disp_enable(True)   # ① 若已被 blackout 关掉，先打开
            self.disp_on = True
        with self.lock:              # ② 立刻推一屏"唤醒中"，别让用户对着黑屏干等
            self.canvas[:] = PAL["bg"]
            txt(self.canvas, "触摸屏唤醒中…", W // 2, H // 2, 36, PAL["dim"], "cm")
            self.conv_rect(0, 0, W, H)
            self.chunk.write(0, self.u16.tobytes(), BUF)
        t0 = time.time()
        self.open_cam()              # ③ 重开摄像头（约 1 s）
        self.dirty = True
        print("  [唤醒] 显示已开 + 摄像头已重开（%.1f s）" % (time.time() - t0), flush=True)
        self.toast_set("已唤醒", 1.5)

    def draw_touch(self, cv):
        """--show-touch：把"程序认为你点在哪儿"画成十字准星。

        用来核对触摸屏坐标映射对不对：手指按在屏幕哪个位置，准星就该出现在同一个位置。
        如果准星和你手指的位置是镜像/旋转的，一眼就能看出来。
        """
        import cv2
        t = self.touch
        age = time.time() - t.last_t
        if age > 3.0:
            return
        x, y = t.last
        col = PAL["ok"] if t.is_down else PAL["accent"]
        cv2.line(cv, (x - 40, y), (x - 8, y), col, 2)
        cv2.line(cv, (x + 8, y), (x + 40, y), col, 2)
        cv2.line(cv, (x, y - 40), (x, y - 8), col, 2)
        cv2.line(cv, (x, y + 8), (x, y + 40), col, 2)
        cv2.circle(cv, (x, y), 8, col, 2)
        rx, ry = t.raw
        s = "触摸 (%d,%d)  原始 ABS=(%d,%d)  第 %d 次" % (x, y, rx, ry, t.n_down)
        bw = text_size(s, 18)[0] + 16
        bx = min(max(4, x - bw // 2), W - bw - 4)
        by = y + 46 if y < H - 90 else y - 70
        rrect(cv, (bx, by, bx + bw, by + 30), BGR(0, 0, 0), r=8, fill=True)
        txt(cv, s, bx + 8, by + 15, 18, col, "lm")

    # ---------------------------------------------------------- 推送
    def conv_rect(self, x0, y0, x1, y1):
        """把 canvas 的一块矩形转成 RGB565 写进常驻 u16 缓冲（其他像素原样保留）"""
        sub = self.canvas[y0:y1, x0:x1]
        a = sub.astype(np.uint16)          # ★ 通道 2 才是 R（cv2 读出来是 BGR），别搞反
        self.u16[y0:y1, x0:x1] = (((a[:, :, 2] >> 3) << 11)
                                  | ((a[:, :, 1] >> 2) << 5)
                                  | (a[:, :, 0] >> 3))

    def push(self):
        t0 = time.time()
        if self.dirty or self.prev_rect is None:
            self.conv_rect(0, 0, W, H)     # 界面有变化 -> 整屏重算
            self.dirty = False
        else:
            x0, y0, x1, y1 = self.prev_rect
            self.conv_rect(x0, y0, x1, y1)  # 稳态 -> 只转预览那块
        self.stat["conv"] += time.time() - t0
        t1 = time.time()
        raw = self.u16.tobytes()
        self.chunk.write(0, raw, len(raw))
        self.stat["push"] += time.time() - t1
        self.stat["n"] += 1
        self._maybe_shot()

    # ★ 2026-10-23：串口调试看不到屏 ⇒ 让 UI 自己把画布存成图片。
    #   触发方式：`touch /dev/shm/_shot.req`；UI 下一帧就把整屏写成 /root/_shot.jpg（缩一半）。
    #   为什么不在外面读 /dev/mem：这块屏不是 framebuffer，且内核 STRICT_DEVMEM 挡着 DDR。
    SHOT_REQ = "/dev/shm/_shot.req"
    SHOT_OUT = "/root/_shot.jpg"

    def _maybe_shot(self):
        try:
            if not os.path.exists(self.SHOT_REQ):
                return
            os.unlink(self.SHOT_REQ)
            from PIL import Image as _I
            a = self.u16
            r = ((a >> 11) & 0x1F).astype(np.uint16) * 255 // 31
            g = ((a >> 5) & 0x3F).astype(np.uint16) * 255 // 63
            b = (a & 0x1F).astype(np.uint16) * 255 // 31
            im = _I.fromarray(np.stack([r, g, b], -1).astype(np.uint8))
            im = im.resize((W // 2, H // 2), _I.LANCZOS)
            im.save(self.SHOT_OUT, quality=58, optimize=True)
            self.toast_set("截图已存 %s" % self.SHOT_OUT, 2.0)
        except Exception as e:
            self.toast_set("截图失败 %s" % e, 2.0)

    # ---------------------------------------------------------- 主循环
    def step_cam(self):
        """取最新一帧并做曝光。**没有新帧就返回 False，不重复渲染** ——
        相机只有 ~12.5 fps，而主循环能跑 30+ fps，不判新帧的话会把同一张图
        反复转换、反复推屏，白烧 CPU 还增加延迟。"""
        if self.grab is None:
            if not self.open_cam():
                time.sleep(0.5)
                return False
        frame, seq = self.grab.take()
        # ★ 注意：self.fps 只在整画时才会刷到屏上（见 chrome_ok 分流）。
        #   所以主循环里有一条"屏上值与实际值不一致就标 dirty"的逻辑补上这一点 ——
        #   否则屏上的"帧率"会永远停在最后一次整画那一刻（实测会一直显示 0.0 fps）。
        #   fps 文字每秒都变，若为它每秒整画一次，就会每秒卡一下（实测整画 ~135 ms）。
        #   所以屏上的 fps 是"上次界面重画时的值"，偏旧但不影响使用；精确值看 /root/ui.log。
        self.fps = self.grab.rate
        # 分辨率真值一变就整画（首帧前 real_wh=(0,0)，右栏会先显示命令行默认值）
        _rw, _rh = getattr(self.grab, "real_wh", (0, 0)) or (0, 0)
        if _rw and (_rw, _rh) != getattr(self, "wh_shown", (0, 0)):
            self.dirty = True
        if frame is None:
            time.sleep(0.003)
            return False
        self.last_seq = seq
        t1 = time.time()
        frame = self.apply_ev(frame)
        self.stat["lut"] += time.time() - t1
        self.last_frame = frame
        if self.shot_pending:
            self.shot_pending = False
            self.do_shot()
        self.frames += 1
        return True

    def dump(self):
        """把当前画布原样存成 PNG = 「屏幕截图」。

        ★ 必须持锁 + copy 一份再写盘。第一版直接在渲染线程改着的 canvas 上
          cv2.imwrite，结果 PNG 是**撕裂**的：imwrite 从上往下逐行编码要几十毫秒，
          这期间渲染线程正处在"预览带填黑"和"贴视频"之间，
          于是存出来的图上半条带是全黑、下半条带才是画面。
          —— 屏上其实是好的，是我的截图工具错了。
        """
        import cv2
        with self.lock:
            snap = self.canvas.copy()
            lf = None if self.last_frame is None else self.last_frame.copy()
            pr = self.prev_rect
        n = self.dump_n
        self.dump_n += 1
        p = "/root/ui_dump_%02d.png" % n
        cv2.imwrite(p, snap)
        cv2.imwrite(DUMP_PATH, snap)
        band = snap[PY0:PY1]
        print("  dump#%d -> %s | prev_rect=%s frame=%s | 条带上半 mean=%.1f 下半 mean=%.1f"
              % (n, os.path.basename(p), pr, None if lf is None else lf.shape,
                 band[:len(band) // 2].mean(), band[len(band) // 2:].mean()), flush=True)
        if lf is not None:
            cv2.imwrite("/root/ui_frame_%02d.png" % n, lf)

    def run_script(self, script):
        """无人工干预的自测序列： tap X,Y | dump | sleep MS | page N | quit"""
        for raw in script.split(";"):
            c = raw.strip()
            if not c:
                continue
            p = c.split()
            try:
                if p[0] == "sleep":
                    time.sleep(float(p[1]) / 1000.0)
                elif p[0] == "tap":
                    x, y = (int(v) for v in p[1].split(","))
                    self.q.put(("down", x, y))
                    time.sleep(0.08)
                    self.q.put(("up", x, y))
                elif p[0] == "dump":
                    time.sleep(0.4)
                    self.dump()
                elif p[0] == "quit":
                    time.sleep(0.4)
                    self.stop = True
                elif p[0] == "state":
                    # queue= 后面按**发送顺序**列出前 6 张 —— 脚本自测多选时靠它核对顺序
                    print("  STATE screen=%s ev=%+.2f auto=%s dirty=%s "
                          "tab=%s(cam%d/alb%d) shown=%d "
                          "queue=%d[%s] page=%d send=%s(%s) touch_down=%d reopen=%d awake=%s idle=%.1fs slept=%d never=%s"
                          % (self.screen, self.ev, self.auto, self.dirty,
                             "cam" if self.gal_tab == 0 else "alb",
                             self.n_cam, self.n_alb, len(self.photos),
                             len(self.queue),
                             ",".join(os.path.basename(p) for p in self.queue[:6]),
                             self.gal_page, self.send_state, self.send_msg,
                             self.touch.n_down, self.touch.n_reopen, self.awake,
                             time.time() - self.last_act, self.n_sleep,
                             self.sleep_never), flush=True)
            except Exception as e:
                print("  script %r 出错: %s" % (c, e), flush=True)
        print("  SCRIPT_DONE", flush=True)

    def run(self):
        self.touch.start()
        if self.a.script:
            threading.Thread(target=self.run_script, args=(self.a.script,), daemon=True).start()
        if self.screen == "cam":
            self.open_cam()
        self.refresh_photos()
        # ★ 2026-10-17：首帧就绪（待机屏已在 setup_display 里显示着）。
        #   主循环第一圈就 render+push 整屏，屏上从"待机屏"换成界面。
        if not self.disp_on:                 # 兜底：真有哪条路把显示关了，这里补开
            self.disp_enable(True)
            self.disp_on = True
        print("  [显示] 首帧就绪，界面接管（之前显示的是待机屏）  uptime=%.1fs" % _uptime(),
              flush=True)
        n_frames = 0
        while not self.stop:
            if self.dump_req:
                self.dump_req = False
                self.dump()
            self.drain()
            # ★ 截图请求放在**主循环**里，而不是只放在 push()：
            #   图库页空闲时根本不 push（没有新帧），只挂 push 会永远不触发。
            self._maybe_shot()

            # ---- 唤醒：睡着时任何触摸都先到这里 ----
            if self.wake_req:
                self.wake_req = False
                self.do_wake()

            # ---- 睡着：什么都不做，只等触摸（不取帧、不渲染、不推屏）----
            if not self.awake:
                # --sleep-blackout：待机满 N 秒才真关显示输出（省电）。
                # 关掉之后屏全黑、提示看不见了，但触摸照样唤醒。
                if self.blackout_at > 0 and self.disp_on:
                    remain = int(self.blackout_at - time.time() + 0.999)
                    if remain <= 0:
                        self.disp_enable(False)
                        self.disp_on = False
                        self.blackout_at = 0.0
                        print("  [休眠] 倒计时结束，已关显示输出（省电）。触摸仍可唤醒。",
                              flush=True)
                    elif remain != self.count_shown:
                        self.count_shown = remain      # 每秒重画一次倒计时
                        self.draw_standby(remain)
                self.poll_send()
                time.sleep(0.05)
                continue

            # ---- 该睡了吗 ----
            #   ★ 发图过程中绝不睡（send_proc 非空就压住），否则会把一次发送拦腰截断，
            #     用户回来看到的是"发送失败"或者更糟：容器发了一半。
            if (self.a.sleep_after > 0 and not self.sleep_never
                    and self.send_proc is None
                    and time.time() - self.last_act > self.a.sleep_after):
                self.do_sleep()
                continue

            # toast / 白闪 这类"只有时间在变"的东西到期时，也必须让界面重画一次
            ov = (time.time() < self.toast_until) or (time.time() < self.flash_until)
            if ov != self.ov_prev:
                self.ov_prev = ov
                self.dirty = True
            if self.a.show_touch and time.time() - self.touch.last_t < 3.0:
                self.dirty = True        # 准星要跟着手指实时动
            self.n_loop += 1
            if self.screen == "cam":
                # ★ 帧率数字只在整画时刷新（见 render() 里 self.fps 那句），
                #   稳态只走 render_preview_only() ⇒ 屏上的"帧率"会永远停在
                #   最后一次整画那一刻的值。实测重启后它一直显示 "0.0 fps"，
                #   看起来像相机没跑（其实是好的）。
                #   这里在"屏上值与实际值不一致"时才标 dirty ⇒ 大约每秒一次整画，
                #   代价 9 ms/s（<1% CPU），值稳定时一次都不多画。
                if self.grab is not None and abs(self.grab.rate - self.fps) >= 0.05:
                    self.dirty = True
                # ★ 同上：曝光时间也必须**跟真值同步**。
                #   相机节点可能被本进程之外的东西改（手工 ctl、相机自己的行为），
                #   而稳态只贴预览、不重画文字 ⇒ 屏上曝光会停在旧值。
                #   这里只要"屏上值"和"相机真值"差 0.5% 以上就整画一次。
                _e = self.hwstat.get("ExposureTime")
                if (self.mode == "exp" and _e and self.exp_shown
                        and abs(_e - self.exp_shown) > max(
                            1.0, self.exp_shown * 5e-3)):
                    self.dirty = True
                newf = self.step_cam()
                self.n_newf += 1 if newf else 0
                # 有新帧就重画；没有新帧但界面状态变了（曝光/toast/白闪）也要重画
                if newf or self.dirty:
                    with self.lock:
                        _t = time.time()
                        if self.dirty or self.chrome_ok is False:
                            self.render()               # 界面状态变了 -> 整画
                            self.chrome_ok = True
                        else:
                            self.render_preview_only()  # 稳态 -> 只贴预览
                        self.stat["render"] = self.stat.get("render", 0.0) + time.time() - _t
                        self.push()
                    n_frames += 1
            else:
                if self.dirty:
                    with self.lock:
                        self.render()
                        self.push()
                time.sleep(0.02)
            self.poll_send()
            if self.a.frames and n_frames >= self.a.frames:
                break
        s = self.stat
        if self.grab is not None:
            print("  取帧线程: 抽帧 %d 次 / 解码 %d 帧 ｜ 主循环 %d 次 / 新帧 %d 次 / 渲染 %d 帧"
                  % (self.grab.n_grab, self.grab.total, self.n_loop, self.n_newf,
                     s["n"]), flush=True)
        self.close_cam()
        if s["n"]:
            print("完成 %d 帧 | 相机实际 %.1f fps（后台取帧线程测量）| 曝光LUT %.1f  "
                  "render %.1f  UI+RGB565 %.1f  写入 %.1f ms ⇒ UI 合计 %.1f ms/帧"
                  % (s["n"], self.fps, s["lut"] / s["n"] * 1000,
                     s.get("render", 0.0) / s["n"] * 1000,
                     s["conv"] / s["n"] * 1000, s["push"] / s["n"] * 1000,
                     (s["lut"] + s.get("render", 0.0) + s["conv"] + s["push"]) / s["n"] * 1000), flush=True)
        print("  tile 调用 %d 次 / 缓存未命中 %d 次 ｜ blit %d 次 / 共 %d 像素"
              % (STAT["tile"], STAT["miss"], STAT["blit"], STAT["blit_px"]), flush=True)
        print("触摸按下次数 = %d  最后坐标 = %s" % (self.touch.n_down, self.touch.last))
        print("UI_DONE")


def check_font_coverage(strict=True):
    r"""启动自检：UI 上**真的会画**的每一个字符，字体里都必须有字形。

    ★ 豆腐块这个坑踩了**三次**：
        第一次：字体子集把空格滤掉了，屏上每个空格都成了 □ 里一个叉；
        第二次：新加了 "等对方应答 BEGIN %s"，方/应/答 不在旧子集里；
        第三次（2026-10-15）：**自检本身是坏的** —— 见下。
      前两次的教训是"要在启动时查"；第三次的教训是"**判据必须是权威的**"。

    ★★ 判据（第三次事故后重写）：
      旧判据 = 把字符渲染到空图上，看 `np.asarray(im).any()`。
      **那是错的**：缺字形时 PIL 画的是 **.notdef 方框** —— 那也"有像素"
      ⇒ 判成"有字形" ⇒ **假阴性**。实测 `墙/钟/耗/非` 缺字形却一路通过自检，
      直到用户先在屏上看见了豆腐块（"失败 rc=7 对方未确认 41s | 全部□□ 41 s"）。

      新判据 = 先用一个**必然不存在**的码位（U+E123，私用区）渲染出 .notdef 的样子，
               任何字符的位图与它**完全相同**（或完全空白）⇒ 判定缺字形。

    ★ 另外：**跳过 docstring**。注释和文档字符串永远不会画到屏上，
      把它们算进来只会让自检越来越难过（★ ⚠ ✗ 这些符号本来也不该进字体）。
      真正上屏的文字有两处来源：本文件的字符串字面量 + `STAGE_TEXT`；
      第三处（脚本日志原文）由 `txt()` 里的运行期 `sanitize()` 兜底。

    ★★ 缺字形时**默认不再拒绝启动**（2026-10-15 改）：
      原来 `strict=True` 是默认，`raise SystemExit` ⇒ **屏上一个字缺字形，整台设备就起不来**
      （`rc.local` 已经跑完、UI 起不来 ⇒ 用户看到一块黑屏，还没有任何提示）。
      实测踩到：新加一句图库提示文案，里面有个 `旁` 不在字体子集里 ⇒ `python exit=1`。
      而**运行期本来就有兜底** —— `txt()` 会对每个字符调 `sanitize()`，没字形的换成 `?`，
      **绝不会画成豆腐块**。既然不会出豆腐块，就没有理由为它拒绝启动。
      ⇒ 改成：默认**大声警告 + 继续**（并打印修法）；要严格请显式加 `--font-strict`
      （做上板前预检时用），彻底跳过用 `--no-font-check`。
    """
    import ast

    src = open(os.path.abspath(__file__), encoding="utf-8").read()
    tree = ast.parse(src)

    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docs.add(id(body[0].value))

    # ★ 还要跳过 `help=`（argparse 的参数说明）。
    #   它们和 docstring 一样**永远不会画到屏上**（只出现在 `--help` 的终端输出里），
    #   算进来只会逼着人去改命令行帮助的措辞。2026-10-15 补：加了 `--font-strict` 的
    #   帮助文本里有个「警」，结果自检报警 —— 而屏上根本不画它。
    helps = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "help" \
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            helps.add(id(node.value))

    chars = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docs and id(node) not in helps):
            chars |= set(node.value)
    chars |= set(" \t")
    todo = sorted(c for c in chars if c.isprintable() and c != " ")

    missing = [c for c in todo if _glyph_missing(c)]
    if missing:
        msg = ("字体缺 %d 个字形，屏上会显示成 '?': %s\n"
               "   修法: 在 PC 上跑  python make_ui_font.py --scan glc_ui.py\n"
               "         重新生成 ui_font.ttf 再 scp 到板子 /root/"
               % (len(missing), "".join(missing)))
        if strict:
            raise SystemExit("!! " + msg)
        print("!! " + msg, flush=True)
    else:
        print("  字体自检: %d 个字符全部有字形（判据=.notdef 比对，已跳过 docstring 与 help=）"
              % len(todo), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", default="auto",
                    help="摄像头设备：auto=自动解析（推荐 —— 实测重启后 videoN 会变号）；"
                         "也可直接给 /dev/videoN 或数字 index")
    ap.add_argument("--cw", type=int, default=640)
    ap.add_argument("--ch", type=int, default=480)
    ap.add_argument("--cam-fps", dest="cam_fps", type=int, default=0,
                    help="向相机请求的帧率（0=不动，用相机默认。实测 640x480 MJPG "
                         "驱动只能到 ~12.5~19 fps，改这个不会更快，但可以试延迟）")
    ap.add_argument("--ev", type=float, default=0.0)
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--exp-us", type=float, default=EXP_START_US,
                    help="开机初始曝光时间 µs（默认 %(default)s = 60 ms；"
                         "相机不支持时自动忽略。注意「复位」按钮的目标是 15 ms，见 EXP_DEFAULT）")
    ap.add_argument("--touch", default="auto",
                    help="触摸屏设备：auto=自动解析（推荐 —— 实测重启后 eventN 会变号，"
                         "摄像头会抢走 event0）；也可直接给 /dev/input/eventN")
    ap.add_argument("--frames", type=int, default=0)
    ap.add_argument("--script", default="")
    ap.add_argument("-v", "--verbose", action="store_true", help="打印每一次触摸/点击")
    ap.add_argument("--show-touch", dest="show_touch", action="store_true",
                    help="在屏上画触摸十字准星（核对坐标映射用）")
    ap.add_argument("--no-font-check", dest="no_font_check", action="store_true",
                    help="跳过启动时的字体覆盖率自检（只在明确知道自己在干什么时用）")
    ap.add_argument("--font-strict", dest="font_strict", action="store_true",
                    help="字体缺字形时**拒绝启动**。默认只警告并继续 —— 见 check_font_coverage 的说明")
    ap.add_argument("--sleep-after", dest="sleep_after", type=float, default=90.0,
                    help="无操作多少秒后熄屏 + 关摄像头（0=永不熄屏，默认 90）")
    ap.add_argument("--sleep-blackout", dest="sleep_blackout", type=float, default=10.0,
                    help="待机后**倒计时多少秒再关显示输出**（默认 10，屏上有「N 秒后将关闭显示」）。"
                         "0 = 不倒数、立即关。想让提示一直可见用 --sleep-keep-sync")
    ap.add_argument("--no-sleep-hint", dest="no_sleep_hint", action="store_true",
                    help="待机时只黑屏、不显示那行灰字提示")
    ap.add_argument("--sleep-keep-sync", dest="sleep_keep_sync", action="store_true",
                    help="显示输出永不关 ⇒ 待机提示一直可见（但省电少）")
    a = ap.parse_args()

    ui = UI(a)

    def on_usr1(sig, frm):
        ui.dump_req = True

    def on_term(sig, frm):
        ui.stop = True

    signal.signal(signal.SIGUSR1, on_usr1)
    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)

    os.makedirs(PHOTO_DIR, exist_ok=True)
    if not os.path.exists(FONT_PATH):
        raise SystemExit("缺字体 %s（用 make_ui_font.py 生成后 scp 过来）" % FONT_PATH)
    if not a.no_font_check:
        check_font_coverage(strict=a.font_strict)
    ui.setup_display()
    ui.run()


if __name__ == "__main__":
    main()
