#!/bin/bash
# 开机后台预热 GLC 常驻引擎（让用户第一张发送不必付 ~7 s 冷载入）。
#
# 为什么单独成文件：以前这段塞在 start_ui_gige.sh 的 `nohup bash -c '...'` 里，
# 单引号内不能带变量、引号还要嵌套，已经踩过两次事故。独立成文件后引号随便用。
#
# 为什么要"等 UI 起来再热"：
#   实测把预热提前到启动器刚起（甚至挪进 glc_boot）会**抢 UI 的初始化**：
#     · +2 s 那版：warm 到 boot+72 s 才完成，比 +20 s 版还慢
#     · 挪进 glc_boot 那版：进度条之后直接花屏（引擎/显示初始化抢在 UI 之前）
#   所以判据不是"固定睡多久"，而是"**UI 进程真的起来了、并给了它 3 s 画首帧**"。
#
# 实测对照（2026-10-23）：
#   固定 sleep 20（等 UI 起后 20 s） → warm 完成于 boot+41.3 s
#   本脚本（UI 进程 +3 s 起跑）      → 见 /root/warm.log 与 warm_engine.log 的 uptime 打点
set -u

LOG=/root/warm_engine.log
U() { cut -d. -f1 /proc/uptime; }

echo "[warm] start uptime=$(U)" >> "$LOG"

# ① 等 UI 进程出现（最多 40 s，避免 UI 挂了在这里永久挂着）
i=0
while [ $i -lt 160 ]; do
    pgrep -f "glc_ui\.py" > /dev/null 2>&1 && break
    sleep 0.25
    i=$((i + 1))
done
echo "[warm] ui seen uptime=$(U) waited=$((i / 4))s" >> "$LOG"

# ② 再给它 3 s 把首帧画出来（这里太短会和它的初始化抢 CPU/NPU）
sleep 3

# ③ 固定小图（放在 /root，不在 photos 里，所以不会进图库）
if [ ! -f /root/_warm256.jpg ]; then
    python3 -c 'from PIL import Image; Image.new("RGB",(256,256),(128,128,128)).save("/root/_warm256.jpg", quality=80)' 2>/dev/null
fi

# ④ 干一次干跑编码（--dry：只编码、不发电台），daemon 常驻 300 s 空闲
echo "[warm] encode start uptime=$(U)" >> "$LOG"
GLC_ALLOW_NO_RADIO=1 GLC_ENC_IDLE=300 bash /root/send_image.sh /root/_warm256.jpg \
    --dry --daemon --small --tag warm >> "$LOG" 2>&1
echo "[warm] done uptime=$(U) rc=$?" >> "$LOG"
exit 0
