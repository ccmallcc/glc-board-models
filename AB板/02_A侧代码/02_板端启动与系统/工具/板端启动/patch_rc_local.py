#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""patch_rc_local.py —— 往 /etc/rc.local 里插「上电自动加载位流」那一行（幂等 + 自动备份）

在板子上跑。可重复执行，已打过就跳过。
"""
import os
import shutil
import time

P = "/etc/rc.local"
MARK = "load_bitstream.sh"
BLOCK = [
    "# GLC 2026-10-15: 上电自动加载 PL 位流（文件名读 /root/glc/current_bitstream）",
    "[ -x /root/glc/load_bitstream.sh ] && bash /root/glc/load_bitstream.sh",
]


def main():
    src = open(P, encoding="utf-8", errors="replace").read()
    if MARK in src:
        print("已经打过补丁，跳过")
        return 0
    bak = P + ".bak_" + time.strftime("%Y%m%d_%H%M%S")
    shutil.copy2(P, bak)
    print("已备份 -> %s" % bak)

    lines = src.split("\n")
    idx = next((i for i, l in enumerate(lines) if "speed_setup.sh" in l), len(lines))
    out = lines[:idx] + BLOCK + [""] + lines[idx:]
    new = "\n".join(out)
    with open(P, "w", encoding="utf-8") as f:
        f.write(new)
    os.chmod(P, 0o755)
    print("已插入到第 %d 行之前（原文件共 %d 行）" % (idx + 1, len(lines)))
    print("---- 新 rc.local 末尾 10 行 ----")
    for l in new.split("\n")[-10:]:
        print("   " + l)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
