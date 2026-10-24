#!/bin/bash
# =============================================================================
#  速率基准.sh —— 量「当前链路每帧真实空口时间」
#
#  为什么要有它：现在**没有任何一个数字**是在"当前生产链路 + B 端在场"下直接量的。
#    仓库里现有的几个数口径互相打架：
#      · 25_GLC容器过空口:43  一帧 324 B ≈ 1.65 s 空口  ← 但那是**发端 200 B/s 节流**下的时间
#      · 34 §4.5              goodput 164~197 B/s（320 B 级帧，200 B/s 节流）
#      · 40 号文              "7 张真正空口只占 4.8 s"（≈0.69 s/张） ← 与上面两个对不上
#    而**生产链路用的 A_send_session.py 是一次性 os.write 整帧、不分块**
#    （24 号文坑 4 说"一次性写整帧会被电台丢"）—— 到底会不会丢、真实一帧多久，
#    只有真发一次才知道。
#
#  它回答三个问题：
#    ① 每帧的**真实 ACK 用时**（= 数据空口 + 对方处理 + ACK 回来）
#    ② **有没有丢帧重试**（第 k 次 > 1 就是丢了；每次丢多付 6 s 等 + 4 s 隔）
#    ③ 实际 goodput 多少 B/s —— 据此判断**要不要开 AT+SYMBOL=6（76.8 kbps）**
#
#  用法（板子上）：
#      bash /root/速率基准.sh              # 发 3 张（默认取相册前 3 张）
#      bash /root/速率基准.sh 5            # 发 5 张
#      bash /root/速率基准.sh 3 --repeat 2 # 同一批连发 2 轮
#
#  前置：
#    ★ B 端已在监听（推荐 80 号文 §三 选项 C 的常驻；至少要把 radio_rx_session.py 挂上）
#    ★ 电台在、两端 SYMBOL/FREQ 一致
#
#  产物：/root/rate_bench/<时间戳>/  完整日志 + 报告.txt
# =============================================================================
set -u

N="${1:-3}"
case "$N" in ''|*[!0-9]*) echo "用法: bash 速率基准.sh [张数] [--repeat R]"; exit 2;; esac
shift || true
EXTRA="$*"

DEV="${GLC_RADIO_DEV:-/dev/ttyUSB0}"
STAMP=$(date +%Y%m%d_%H%M%S)
DIR=/root/rate_bench/$STAMP
mkdir -p "$DIR"
REPORT="$DIR/报告.txt"

echo "=== 速率基准  $STAMP ==="
echo

# ---------------------------------------------------------------- 前置检查
if [ ! -c "$DEV" ]; then
    echo "!! 找不到电台 $DEV —— 先确认 USB 电台插好（lsusb 应有 1a86:7523）"
    exit 3
fi
echo "电台设备: $DEV"

# 选图：**相册在前、相机在后**，并按文件名升序 —— 顺序稳定，便于两次跑对比
IMGS=""
n=0
for d in /root/photos/album /root/photos; do
    for f in $(ls -1 "$d"/*.jpg "$d"/*.jpeg "$d"/*.png 2>/dev/null | sort); do
        [ "$n" -ge "$N" ] && break
        IMGS="$IMGS $f"
        n=$((n + 1))
    done
    [ "$n" -ge "$N" ] && break
done

if [ "$n" -lt "$N" ]; then
    echo "!! 只找到 $n 张图（要 $N 张）。先往 /root/photos/album/ 拷几张。"
    exit 4
fi
echo "本次发送 $n 张:"
for f in $IMGS; do echo "    $f"; done
echo
echo "★★ 确认 B 端已经在监听！等不到 BEGIN 会在 30 s 后放弃（rc=7）。"
echo "   3 秒后开始…（Ctrl-C 可取消）"
sleep 3
echo

# ---------------------------------------------------------------- 正式发送
echo "--- 调 send_image.sh（编码 + 一次会话发 N 张 = 命令行路径）---"
# shellcheck disable=SC2086
bash /root/send_image.sh $IMGS --dry 2>&1 | tee "$DIR/send_dry.log" >/dev/null
if [ ! -f /root/send_work/last.log ]; then
    echo "!! 没找到 /root/send_work/last.log，编码可能失败"
    exit 5
fi
cp -f /root/send_work/last.log "$DIR/encode.log"

# 真正发（同一批容器）：send_image.sh 不带 --dry 会自己编码一遍，
# 这里直接用容器目录跑 A_send_session，避免重复编码
WORK=$(readlink -f /root/send_work/latest 2>/dev/null)
GLCS=$(ls -1 "$WORK"/*.glc 2>/dev/null | sort)
if [ -z "$GLCS" ]; then echo "!! 没找到容器（$WORK）"; exit 6; fi
echo "容器:"
for g in $GLCS; do printf "    %-24s %6s B  %s\n" "$(basename "$g")" "$(stat -c%s "$g")" "$(md5sum "$g" | cut -c1-8)"; done
echo

# shellcheck disable=SC2086
( cd /root && timeout 600 python3 -u /root/A_send_session.py $GLCS $EXTRA ) 2>&1 | tee "$DIR/session.log"
RC=${PIPESTATUS[0]}
echo
echo "A_send_session rc=$RC"

# ---------------------------------------------------------------- 解析
python3 /root/速率基准_解析.py "$DIR/session.log" "$DIR/encode.log" "$RC" > "$REPORT"

cat "$REPORT"
echo
echo "完整日志: $DIR/"
echo "  session.log  发送全程    encode.log  编码     报告.txt  本报告"
