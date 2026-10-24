#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""patch_rc_local_ui.py —— 往 /etc/rc.local 末尾加「开机自启触摸屏界面」那一行（幂等 + 自动备份）

在板子上跑。可重复执行，已打过就跳过。

为什么放**最后**：
  1. rc.local 第 17 行已经 `systemctl start sshd` ⇒ 万一 UI 起不来，SSH 照样能进去救；
  2. 必须排在 `speed_setup.sh` **之后** —— UI 的发送链路依赖它建的
     `/root/glc/pack/full_img0` 与 `/root/glc/run` 两个 /dev/shm 软链。
"""
import os
import shutil
import time

P = "/etc/rc.local"
MARK = "start_ui.sh"
BLOCK = [
    "",
    "# GLC 2026-10-15: 开机自启触摸屏界面",
    "#   放在最后 ⇒ sshd 已起（UI 挂了也能 SSH 进去救）+ speed_setup 已建好 tmpfs 软链",
    "#   无操作 90 s 会进待机（屏全黑）；想永不待机就在下面那行前加 GLC_UI_SLEEP=0",
    "[ -x /root/start_ui.sh ] && bash /root/start_ui.sh >/var/log/glc_ui_boot.log 2>&1",
]


def main():
    src = open(P, encoding="utf-8", errors="replace").read()
    if MARK in src:
        print("已经打过补丁，跳过")
        return 0
    bak = P + ".bak_" + time.strftime("%Y%m%d_%H%M%S")
    shutil.copy2(P, bak)
    print("已备份 -> %s" % bak)

    new = src.rstrip("\n") + "\n" + "\n".join(BLOCK) + "\n"
    with open(P, "w", encoding="utf-8") as f:
        f.write(new)
    os.chmod(P, 0o755)
    print("已追加到末尾（原文件 %d 行 → 现在 %d 行）"
          % (len(src.split("\n")), len(new.split("\n"))))
    print("---- 新 rc.local 末尾 8 行 ----")
    for l in new.split("\n")[-8:]:
        print("   " + l)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
