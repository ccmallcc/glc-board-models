#!/bin/bash
# radio_dev.sh —— 解析电台的串口节点（**不要写死 /dev/ttyUSB0**）
#
# ★ 为什么需要：
#   USB 串口的编号来自**枚举顺序**，不是固定身份。摄像头/触摸屏已经改成
#   按设备名解析（见 71 号文，实测两次重启节点号各变一轮都被自动吃掉），
#   **电台是最后一个还写死编号的地方**（板端 30+ 个脚本里都是 /dev/ttyUSB0）。
#
#   什么时候会变号：**再插一个 USB 串口设备**（CH340/CP210x/FTDI…），
#   电台就可能从 ttyUSB0 变成 ttyUSB1 ⇒ 所有脚本都找不到电台。
#   （机理判断，本次**没有**用第二个 USB 串口设备实测过。）
#
#   换 USB 端口 / 换插拔顺序：只要**板子上只有一个 USB 串口设备**，编号仍是 ttyUSB0
#   ⇒ 端口和顺序**不影响电台**（这一点与摄像头/触摸屏一样安全）。
#
# 用法：
#   RADIO="$(bash /root/glc/radio_dev.sh)"     # 找到就输出 /dev/ttyUSBn，找不到输出空 + rc=1
#   GLC_RADIO_IDS="1a86:7523 10c4:ea60" bash /root/glc/radio_dev.sh   # 覆盖匹配的 VID:PID
#
# 说明：A_send_session.py 早就支持 `GLC_RADIO_DEV` 环境变量（第 44 行），
#       所以调用方只要 export 一下即可，不用改那个 Python。
set -u

IDS="${GLC_RADIO_IDS:-1a86:7523}"

for t in /sys/class/tty/ttyUSB*; do
    [ -e "$t" ] || continue
    # /sys/class/tty/ttyUSB0/device -> ../../../ttyUSB0
    #   再往上两级才是 USB 设备（再往上一级是 hub，会读到 0424:2514 —— 实测踩过）
    v="$(cat "$t/device/../../idVendor"  2>/dev/null)"
    p="$(cat "$t/device/../../idProduct" 2>/dev/null)"
    [ -n "$v" ] && [ -n "$p" ] || continue
    for id in $IDS; do
        if [ "$v:$p" = "$id" ]; then
            echo "/dev/$(basename "$t")"
            exit 0
        fi
    done
done

exit 1
