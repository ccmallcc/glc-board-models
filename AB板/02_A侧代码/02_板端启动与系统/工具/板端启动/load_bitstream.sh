#!/bin/bash
# GLC 2026-10-15: 上电自动加载 PL 位流（由 /etc/rc.local 调用）
#
#   读 /root/glc/current_bitstream 里的一行文件名，加载 /lib/firmware/<名字>。
#   换位流只改那个文本文件，不用动 rc.local。
#
#   设计原则：**永远 exit 0** —— 位流加载失败绝不能阻塞系统启动
#             （Linux 起不来我们就连不上了；PL 没配上还能 SSH 进去再手动换）
#
#   用法: load_bitstream.sh [--dry-run]
set -u

DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

FWMGR=/sys/class/fpga_manager/fpga0
LIST=/root/glc/current_bitstream
LOG=/var/log/glc_bitstream.log

log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

[ -d "$FWMGR" ] || { log "没有 $FWMGR（FPGA manager 未注册），跳过"; exit 0; }
[ -f "$LIST" ]  || { log "没有 $LIST，跳过"; exit 0; }

# 取第一行非空、非注释内容，去掉空白
NAME=$(sed -e 's/#.*//' -e 's/[[:space:]]//g' "$LIST" | grep -v '^$' | head -1)
[ -n "$NAME" ] || { log "$LIST 是空的，跳过"; exit 0; }

FW="/lib/firmware/$NAME"
[ -f "$FW" ] || { log "!! /lib/firmware/$NAME 不存在 —— current_bitstream 写错了吗？跳过"; exit 0; }

log "准备加载 $NAME（$(stat -c%s "$FW") B）  dry=$DRY"

if [ "$DRY" = "1" ]; then
    log "  [dry-run] 实际会执行: echo $NAME > $FWMGR/firmware"
    log "  [dry-run] 当前 state = $(cat $FWMGR/state 2>/dev/null)"
    exit 0
fi

if echo "$NAME" > "$FWMGR/firmware" 2>>"$LOG"; then
    log "  加载完成，state = $(cat $FWMGR/state 2>/dev/null)"
else
    log "  !! 加载失败 —— 常见原因：bin 没做『每 4 字节组内反转』"
fi

# ---------------------------------------------------------------------------
# ★ 加载完立刻拉掉 HDMI 同步门控 —— 否则屏上是**花屏**（2026-10-15 实测）
#
#   为什么：位流一配置，PL 的复位默认值就是
#       disable_hdmi = 0  (frame_ctrl.v:821)  ⇒ display_en = ~0 = 1 ⇒ **TMDS 立刻开始输出**
#       vtc_enable   = 0  (frame_ctrl.v:1137) ⇒ 视频源选 **cam_***，不是 DDR 帧缓冲
#                                              (frame_trans.sv:184-186 的三目 mux)
#   而 cam_vs / cam_de / cam_rgb 是**没有任何管脚约束的悬空输入**（约束文件里查不到）
#   ⇒ 悬空数据被当视频扫出去 ⇒ **花屏**。
#
#   加位流自启**之前**看不到这个现象：PL 根本没被配置 ⇒ 没有 TMDS ⇒ 显示器报无信号。
#   所以这不是"坏了"，是"把 PL 提前配好之后暴露了它上电时的默认画面"。
#
#   处置：写 0x40080078 = 1 ⇒ display_en = 0 ⇒ 门控掉 timing_hs/vs/de
#         ⇒ 显示器丢同步进待机、**背光灭、屏干净**。起 UI 时 start_ui.sh 会写回 0 并打开显示。
#   （板上已实测：写 1 后背光灭；写 0 恢复。）
#
#   不想要这个行为就设 GLC_KEEP_SYNC=1。
# ---------------------------------------------------------------------------
if [ "${GLC_KEEP_SYNC:-0}" = "1" ]; then
    log "  GLC_KEEP_SYNC=1 ⇒ 保留 HDMI 同步（上电可能花屏，按需）"
elif python3 /root/boot_splash.py --pct 15 --text "加载位流" >/dev/null 2>&1; then
    # ★ 2026-10-23：**先画进度条，不要先拉黑**。
    #   老做法是"先 0x40080078=1 拉黑、稍后再画"，结果监视器要经历
    #   黑→蓝→黑→蓝 两次"无信号"跳变（用户实测看到的正是这个）。
    #   boot_splash 自己会：写帧 → 切 VTC → 开显示 → 最后放开 HDMI 同步，
    #   所以只要它能跑通，就**一次跳变**：从"无信号"直接到进度条画面。
    log "  已画 15% 进度条（boot_splash 自己打开 HDMI 同步，避免多次黑/蓝跳变）"
elif busybox devmem 0x40080078 32 1 >/dev/null 2>&1; then
    log "  !! 进度条画不出来 ⇒ 退回老做法：拉掉 HDMI 同步（屏黑但干净）"
    # ★ 2026-10-23：别让这 10 秒全黑 —— 打一帧进度条（它在同一次里就把同步打开）。
else
    log "  !! 写 0x40080078 失败（busybox devmem 不可用？）—— 屏上可能出现花屏"
fi
exit 0
