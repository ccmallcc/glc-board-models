#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""patch_radio_dev.py —— 把「写死 /dev/ttyUSB0」换成「按 USB id 解析」（幂等 + 自动备份）

在板子上跑。改两个入口脚本（`A_send_session.py` 不用改：它第 44 行已经支持
`GLC_RADIO_DEV` 环境变量）。

做法：
  1. 在 shebang 之后插一段解析块（export GLC_RADIO_DEV，解析不到回退 /dev/ttyUSB0）
  2. 把**代码行**（非注释行）里的 /dev/ttyUSB0 换成 "$GLC_RADIO_DEV"
     注释行保持原样 —— 那些是在讲"历史上写死过"，改了反而看不懂
"""
import os
import shutil
import time

TARGETS = ["/root/send_image.sh", "/root/ui_send.sh"]
MARK = "radio_dev.sh"          # 已打过补丁的标志

RESOLVE = """
# ---- GLC 2026-10-15: 电台设备按 USB id 解析，**不写死 ttyUSBn** ----
#   为什么：USB 串口编号来自**枚举顺序**；再插一个 USB 串口设备，电台就可能变 ttyUSB1。
#   摄像头/触摸屏早改成按名字解析了（见 71 号文），这是最后一个写死的地方。
#   A_send_session.py 第 44 行已经支持 GLC_RADIO_DEV ⇒ 这里只要 export。
if [ -z "${GLC_RADIO_DEV:-}" ]; then
    GLC_RADIO_DEV="$(bash /root/glc/radio_dev.sh 2>/dev/null || true)"
    [ -n "$GLC_RADIO_DEV" ] || GLC_RADIO_DEV=/dev/ttyUSB0
    export GLC_RADIO_DEV
fi
"""


def patch(path):
    src = open(path, encoding="utf-8", errors="replace").read()
    if MARK in src:
        print("  %-28s 已打过，跳过" % os.path.basename(path))
        return
    bak = path + ".bak_" + time.strftime("%Y%m%d_%H%M%S")
    shutil.copy2(path, bak)

    lines = src.split("\n")

    # 1) **先**替换代码行里的 /dev/ttyUSB0
    #    ⚠️ 顺序很重要：第一次写反了（先插入、后替换），结果解析块里那句回退
    #       `GLC_RADIO_DEV=/dev/ttyUSB0` **也被替换掉**，变成
    #       `GLC_RADIO_DEV="$GLC_RADIO_DEV"` —— 回退成了空操作，解析失败时**没有回退**。
    #       所以：先替换已有内容，再插入新块（新块就不在扫描范围里了）。
    n_rep = 0
    for i, ln in enumerate(lines):
        s = ln.lstrip()
        if s.startswith("#"):          # 注释行不动（那些在讲"历史上写死过"）
            continue
        if "/dev/ttyUSB0" in ln:
            lines[i] = ln.replace("/dev/ttyUSB0", '"$GLC_RADIO_DEV"')
            n_rep += 1

    # 2) 再插解析块：放在 shebang 之后
    at = 1 if lines and lines[0].startswith("#!") else 0
    lines = lines[:at] + RESOLVE.split("\n") + lines[at:]

    open(path, "w", encoding="utf-8").write("\n".join(lines))
    os.chmod(path, 0o755)
    print("  %-28s 已改 %d 处，备份 %s" % (os.path.basename(path), n_rep, os.path.basename(bak)))


def main():
    for p in TARGETS:
        if not os.path.exists(p):
            print("  %-28s 不存在，跳过" % os.path.basename(p))
            continue
        patch(p)
    print("PATCH_RADIO_DEV_DONE")


if __name__ == "__main__":
    main()
