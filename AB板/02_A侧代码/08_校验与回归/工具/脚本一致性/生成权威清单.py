#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 工具/权威清单.tsv —— md5 全部自动填，并与板上实测值交叉核对。

为什么要生成而不是手写：手抄 md5 一定出错，而且出错没人发现。
这个脚本对每个"部署"条目断言 [仓库文件 md5] == [板上 md5]，不等就报错、不写文件。
"""
import os
import sys
import hashlib

REPO = r"E:\fudanwei\GLC-共享包"
BOARD = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "证据", "board_md5.txt")
OUT = os.path.join(REPO, "工具", "权威清单.tsv")

# (类型, 板端路径, 仓库路径, 说明)
E = [
    ("部署", "/root/glc/load_bitstream.sh",   "工具/板端启动/load_bitstream.sh",   "开机① 热加载位流；随即写 0x40080078=1 让屏黑（防花屏）"),
    ("部署", "/root/speed_setup.sh",          "工具/板端脚本/speed_setup.sh",      "开机② tmpfs 软链 / 预热 6 模型 / 按位流指纹选编码路径"),
    ("部署", "/root/start_ui.sh",             "工具/触摸屏UI/start_ui.sh",         "开机③ 等 USB 设备就绪后起 UI（--stop/--fg/--touch/--wake 手动入口）"),
    ("部署", "/root/glc_ui.py",               "工具/触摸屏UI/glc_ui.py",           "触摸屏 UI 主程序（拍照/发送/预览/待机）"),
    ("部署", "/root/ui_font.ttf",             "工具/触摸屏UI/ui_font.ttf",         "UI 中文字体，1115 码位；缺字形会画成方框"),
    ("部署", "/root/ui_send.sh",              "工具/触摸屏UI/ui_send.sh",          "UI「发送」按钮调用的封装"),
    ("部署", "/root/send_image.sh",           "工具/板端脚本/send_image.sh",       "命令行发图入口（编码 + 电台发射）"),
    ("部署", "/root/glc/radio_dev.sh",        "工具/板端启动/radio_dev.sh",        "按 1a86:7523 解析电台设备节点，不写死 ttyUSBn"),
    ("部署", "/root/A_send_session.py",       "工具/无线/A_send_session.py",       "电台会话协议发送端；第 44 行认 GLC_RADIO_DEV"),
    ("部署", "/root/glcenc_daemon.py",        "工具/电台发图/glcenc_daemon.py",    "常驻编码守护进程（单张 ~1.4 s）"),
    ("部署", "/root/glc/glc_rsd.py",          "工具/常驻引擎/glc_rsd.py",          "单张编码主链（RSD）"),
    ("部署", "/root/glc/glc_rsd_cpu.py",      "工具/常驻引擎/glc_rsd_cpu.py",      "单张编码 CPU 路径"),
    ("部署", "/root/glc/glc_batch_rsd.py",    "工具/常驻引擎/glc_batch_rsd.py",    "常驻批处理 PL rANS（0.60 s/张）"),
    ("部署", "/root/glc/glc_batch_cpu.py",    "工具/常驻引擎/glc_batch_cpu.py",    "常驻批处理 CPU（0.89 s/张）"),
    ("部署", "/root/glc/glc_yh_stats.py",     "工具/常驻引擎/glc_yh_stats.py",     "量化统计（诊断用）"),
    ("部署", "/root/glc/glc_board_full.py",   "工具/板端程序/glc_board_full.py",   "全链路参考比对（产物写 pack/full_*，绝不覆盖参考）"),
    ("部署", "/root/glc/pack_full.sh",        "工具/板端脚本/pack_full.sh",        "打包"),
    ("部署", "/root/glcdec/decode_board.py",  "工具/解码端诊断/decode_board.py",   "板端解码（B 方向；解码链目前暂停）"),
    ("部署", "/root/radio_check.py",          "工具/板端脚本/radio_check.py",      "电台参数核对。★2026-10-15 前这里放的是**不含 +++ 的事故版**(84行)，已换成修好版(113行)"),
    ("部署", "/root/radio_watch.sh",          "工具/板端脚本/radio_watch.sh",      "电台监听"),
    ("部署", "/root/single_timing.sh",        "工具/电台发图/single_timing.sh",    "单张计时"),
    ("部署", "/root/ui_test4.sh",             "工具/触摸屏UI/ui_test4.sh",         "UI 回归测试脚本"),
    ("部署", "/root/board_models_md5.sh",     "工具/板端脚本/board_models_md5.sh", "列出板端 5 个 _ZG 产物的 md5+字节，用于核模型完整性"),
    # ---- 镜像：内容必须与权威逐字节相同的第二份 ----
    #    镜像行的「板端路径」列填**权威仓库路径**（见表头说明）
    ("镜像", "工具/板端脚本/send_image.sh", "工具/电台发图/send_image.sh",
     "第二份副本；必须与权威逐字节相同。改代码请改权威那份"),
    ("镜像", "工具/run_sim.sh", "工具/板端脚本/run_sim.sh",
     "板端脚本/README.md:62 本来就写明它是拷贝；实测 e2sim.sh/c2sim.sh 都 exec 到权威那份"),
]


def md5f(p):
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


board = {}
for line in open(BOARD, encoding='utf-8', errors='replace'):
    p = line.split()
    if len(p) == 2:
        board[p[1]] = p[0]

rows, errs = [], []
for typ, bpath, rpath, note in E:
    fp = os.path.join(REPO, rpath.replace('/', os.sep))
    if not os.path.isfile(fp):
        errs.append("仓库缺文件: %s" % rpath)
        continue
    m = md5f(fp)
    sz = os.path.getsize(fp)
    if typ == "部署":
        bm = board.get(bpath)
        if bm is None:
            errs.append("板上找不到: %s" % bpath)
        elif bm != m:
            errs.append("md5 不符 %s\n      板端 %s\n      仓库 %s" % (bpath, bm, m))
    else:                                   # 镜像：必须与权威当前内容相同
        fp2 = os.path.join(REPO, bpath.replace('/', os.sep))
        if not os.path.isfile(fp2):
            errs.append("镜像指向的权威不存在: %s" % bpath)
        else:
            m2 = md5f(fp2)
            if m2 != m:
                errs.append("镜像已偏离权威: %s (%s) != %s (%s)"
                            % (rpath, m[:8], bpath, m2[:8]))
    rows.append((typ, bpath, rpath, m, sz, note))

if errs:
    print("!! 拒绝生成，先解决以下问题：")
    for e in errs:
        print("   - " + e)
    sys.exit(1)

lines = [
    "# GLC 脚本权威清单  v1  2026-10-15",
    "# 生成方式: 工具/校验_权威与板端.py --regen  (md5 自动填，且已与板上实测值逐条核对)",
    "#",
    "# 列:  类型 <TAB> 板端路径 <TAB> 权威仓库路径 <TAB> md5 <TAB> 字节 <TAB> 说明",
    "#   部署 = 会真的部署到板子上跑。第2列=板端路径，第3列=权威仓库路径",
    "#          改代码请改「权威仓库路径」这一份，再传上去",
    "#   镜像 = 仓库里的第二份副本。第2列=**权威仓库路径**，第3列=镜像路径",
    "#          镜像内容必须与权威逐字节相同（校验脚本会查）",
    "#",
    "# 校验: python3 工具/校验_权威与板端.py",
]
for typ, bpath, rpath, m, sz, note in rows:
    lines.append("\t".join([typ, bpath, rpath, m, str(sz), note]))
lines.append("")

with open(OUT, "w", encoding="utf-8", newline="\n") as f:
    f.write("\n".join(lines))

print("已写 %s" % OUT)
print("  部署 %d 条 / 镜像 %d 条" % (sum(1 for r in rows if r[0] == "部署"),
                                     sum(1 for r in rows if r[0] == "镜像")))
