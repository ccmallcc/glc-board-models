#!/bin/sh
# ============================================================================
#  长挂混合_上板验证.sh —— UI 挂着不动，按"混合节奏"连发 10 分钟（板子上跑）
#  （GLC A 侧，2026-10-17）
#
#  节奏（每分钟一个 60 s 周期 × MINS 个周期）：
#    前 30 s：t=0 / 10 / 20 各发 **1 张**（单独发）
#    后 30 s：t=30 起 **背靠背连发 5 张**
#  ⇒ 每分钟 8 张，10 分钟 80 张。
#
#  ★ 为什么默认走"编码"而不是真实电台发送
#  --------------------------------------
#  实测：B 端没应答时，一次 `ui_send.sh` 要 **32 s**（编码只占 1 s，其余是 BEGIN 重试 3 次），
#  每 10 s 一张的节奏根本插不进去（10 分钟最多 18 张）。
#  所以默认 MODE=enc：走 `send_image.sh --dry --daemon`，**和 UI 用的是同一条编码路径**，
#  只是不走电台。想看真实发送就 `MODE=real`（节奏会被 32 s 拖慢，脚本会如实记账）。
#
#  看什么（判据写死，任一不满足退 1）
#  ---------------------------------
#    ① 每个容器的 md5 必须**完全相同**（全程同一张图）
#    ② UI 进程 RSS 涨幅 < 50 MB
#    ③ USB 三件套（电台 1a86:7523 / 摄像头 0c45:6341 / 触摸 1a86:e5e3）全程在位
#    ④ 内核 Oops 不新增
#
#  用法：sh 长挂混合_上板验证.sh [MINS]     # 默认 10 分钟
#        MODE=real sh 长挂混合_上板验证.sh 1
# ============================================================================
MINS=${1:-10}
IMG=${IMG:-/root/send_work/_daemon_in/IMG_0001.jpg}
MODE=${MODE:-enc}
LOG=${LOG:-/root/长挂混合.log}
: > "$LOG"

UIPID=$(pgrep -f "glc_ui" | head -1)
DPID=$(python3 /root/glcenc_client.py PING 2>/dev/null | awk '{print $2}')
USB_RE='1a86:7523|0c45:6341|1a86:e5e3'

snap() {   # $1 = 标签
    U=$(ps -o rss= -p "$UIPID" 2>/dev/null | tr -d ' '); [ -n "$U" ] || U=0
    D=$(ps -o rss= -p "$DPID" 2>/dev/null | tr -d ' '); [ -n "$D" ] || D=0
    N=$(lsusb | grep -cE "$USB_RE")
    O=$(dmesg | grep -c Oops)
    A=$(free -m | awk '/Mem:/{print $7}')
    # ★ fd 也要看：PL 模式下 RegWin 每帧开 /dev/mem+mmap，做成单例后必须**不再增长**
    F=$(ls /proc/"$DPID"/fd 2>/dev/null | wc -l)
    echo "$(date +%H:%M:%S) SNAP $1 ui=${U} daemon=${D} fd=${F} usb=${N} oops=${O} avail=${A}" >> "$LOG"
}

send1() {  # $1 = 标签
    T0=$(date +%s%N)
    if [ "$MODE" = real ]; then
        OUT=$(bash /root/ui_send.sh "$IMG" 2>&1)
        RC=$?
        DR=$(echo "$OUT" | grep -o 'UI_SEND_DONE rc=[0-9]*' | head -1)
    else
        OUT=$(GLC_ENC_IDLE=300 bash /root/send_image.sh "$IMG" --dry --daemon 2>&1)
        RC=$?
        DR=$(echo "$OUT" | grep -o 'OK [^ ]* [0-9]* [0-9a-f]\{32\}' | head -1)
    fi
    DT=$(( ($(date +%s%N) - T0) / 1000000 ))
    M=$(md5sum /root/send_work/latest/IMG_0001.glc 2>/dev/null | cut -c1-32)
    echo "$(date +%H:%M:%S) SEND $1 rc=${RC} dt=${DT}ms md5=${M:-none} ${DR}" >> "$LOG"
}

echo "=== 长挂混合：${MINS} 分钟，MODE=${MODE}，图=$IMG ===" | tee -a "$LOG"
echo "UI pid=$UIPID  daemon pid=$DPID" | tee -a "$LOG"
snap start
START=$(date +%s)
m=1
while [ $m -le "$MINS" ]; do
    base=$(( START + (m - 1) * 60 ))
    for off in 0 10 20; do
        now=$(date +%s)
        [ $((base + off)) -gt "$now" ] && sleep $(( base + off - now ))
        send1 "m${m}_single${off}"
    done
    now=$(date +%s)
    [ $((base + 30)) -gt "$now" ] && sleep $(( base + 30 - now ))
    k=1
    while [ $k -le 5 ]; do send1 "m${m}_burst${k}"; k=$((k + 1)); done
    snap "m${m}"
    m=$((m + 1))
done
snap end

echo "=== 汇总 ===" | tee -a "$LOG"
echo "  发送次数: $(grep -c ' SEND ' "$LOG")" | tee -a "$LOG"
echo "  md5 去重: $(grep ' SEND ' "$LOG" | sed -E 's/.*md5=([0-9a-f]+).*/\1/' | sort -u | tr '\n' ' ')" | tee -a "$LOG"
echo "  失败(rc!=0): $(grep ' SEND ' "$LOG" | grep -vc 'rc=0 ')" | tee -a "$LOG"
echo "  耗时: $(grep ' SEND ' "$LOG" | sed -E 's/.*dt=([0-9]+)ms.*/\1/' | sort -n | awk 'NR==1{min=$1} {s+=$1; n++} END{printf "min=%d avg=%d max=%d ms", min, s/n, $1}')" | tee -a "$LOG"
grep SNAP "$LOG" | tee -a "$LOG"
