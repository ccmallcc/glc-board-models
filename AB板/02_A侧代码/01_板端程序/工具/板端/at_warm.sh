#!/bin/bash
# 开机把电台送进透传态，并写好 /var/run/glc_radio_warm 标记。
#
# 为什么单独一个文件：这段逻辑原来嵌在 start_ui_gige.sh 的
#   `nohup bash -c '...'` 里，单引号内变量不继承、引号又要嵌套，
#   连续踩了两次（一次写成空标记、一次把脚本引号弄坏）。
#   独立成文件后，引号随便用，`bash -n` 也能单独验。
#
# 为什么要它：ui_send.sh 第一次发送时若标记不存在，会重做一次 **8.2 s** 的 AT 自检。
#   在 GigE 启动链里，这段预热以前只存在于 start_ui.sh（USB 那条路），
#   所以标记文件从不生成 ⇒ 每次开机第一张都要多付 8.2 s。
#
# 语义：**只有 AT 自检成功才写标记**；失败不写，下次真发送会自己重做（不会误判）。
set -u

DEV=$(bash /root/glc/radio_dev.sh 2>/dev/null || true)
if [ -z "${DEV:-}" ] || [ ! -c "$DEV" ]; then
    echo "[at_warm] 没有电台设备（DEV=${DEV:-空}），跳过"
    exit 0
fi
READY=$(stat -c %Z "$DEV" 2>/dev/null || echo '')
if [ -z "$READY" ]; then
    echo "[at_warm] 拿不到 $DEV 的 ctime，跳过"
    exit 0
fi

if [ -f /var/run/glc_at_warming ]; then
    echo "[at_warm] 已有人在自检（glc_at_warming 存在），不重复"
    exit 0
fi
: > /var/run/glc_at_warming
trap 'rm -f /var/run/glc_at_warming' EXIT

if python3 -u /root/A_send_session.py --at-only > /root/boot_at.log 2>&1; then
    printf '%s\n' "$READY" > /var/run/glc_radio_warm
    echo "[at_warm] OK 标记=$READY（$DEV）"
else
    echo "[at_warm] 自检失败，不写标记；下次发送会自己重做"
    tail -3 /root/boot_at.log 2>/dev/null
fi
exit 0
