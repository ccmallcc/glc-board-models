#!/bin/sh
# ============================================================================
#  内存长跑_上板验证.sh —— 常驻编码器连发 N 张，看会不会把内存吃光
#  （GLC A 侧，2026-10-17）
#
#  为什么要有它
#  ------------
#  2026-10-17 查"改完会不会爆内存"时实测发现：`glc_rsd.py` 里 `sub.tin.append(t_new)`
#  只增不减，常驻 daemon 每帧攒 8 个输入 tensor ⇒ **3.9 MB/帧**，从 532 MB 可用算
#  约 **137 帧（2 分钟）就 OOM**。修掉之后需要一条能复现的判据盯着它。
#
#  判据（写死，防止"看着没事"就放过）
#  --------------------------------
#    ① 所有帧的容器 md5 必须相同（画面同一张 ⇒ 产物必须一样）
#    ② 最后一个采样块的 RSS 增量 < 第一个块的 1/3  ⇒ 才算进了平台期
#    ③ 可用内存全程不得跌破 MIN_FREE（默认 150 MB）
#  三条里任何一条不满足，退出码 1。
#
#  用法（在 PC 上跑，需要能 ssh 到板子）：
#      sh 内存长跑_上板验证.sh            # 默认 6 块 × 20 帧 = 120 帧
#      BLOCKS=3 PER=10 sh 内存长跑_上板验证.sh
# ============================================================================
set -u
BLOCKS=${BLOCKS:-6}
PER=${PER:-20}
MIN_FREE=${MIN_FREE:-150}
IMG=${IMG:-/root/send_work/_daemon_in/IMG_0001.jpg}
SSH="ssh -i $HOME/.ssh/id_board -o BatchMode=yes -o StrictHostKeyChecking=no root@192.168.1.2"

rss()  { $SSH "PID=\$(python3 /root/glcenc_client.py PING | awk '{print \$2}'); ps -o rss= -p \$PID"; }
free_mb() { $SSH "free -m | awk '/Mem:/{print \$7}'"; }

echo "=== 内存长跑：$BLOCKS 块 × $PER 帧 = $((BLOCKS*PER)) 帧，同一张图 ==="
$SSH "python3 /root/glcenc_client.py PING" || { echo "daemon 没在跑，先起：GLC_ENC_IDLE=0 python3 /root/glcenc_daemon.py start"; exit 2; }

R0=$(rss); F0=$(free_mb)
[ -z "$R0" ] && { echo "拿不到 daemon RSS"; exit 2; }
echo "起点: RSS=${R0} kB  可用=${F0} MB"

PREV=$R0
FIRST_DELTA=0
LAST_DELTA=0
b=1
while [ $b -le $BLOCKS ]; do
    A=""
    i=1
    while [ $i -le $PER ]; do A="$A f$b$i=$IMG"; i=$((i+1)); done
    $SSH "python3 /root/glcenc_client.py ENCBATCH /root/send_work/_memrun $A" > /tmp/memrun_$b.txt 2>&1
    CUR=$(rss); FR=$(free_mb)
    D=$((CUR-PREV))
    echo "  $((b*PER)) 帧: RSS=${CUR} kB (本块 +${D})  可用=${FR} MB"
    [ $b -eq 1 ] && FIRST_DELTA=$D
    LAST_DELTA=$D
    PREV=$CUR
    if [ "$FR" -lt "$MIN_FREE" ]; then echo "!! 可用内存 $FR MB 跌破 $MIN_FREE MB"; exit 1; fi
    b=$((b+1))
done

TOTAL=$((PREV-R0))
N=$((BLOCKS*PER))
echo "总增长 ${TOTAL} kB / ${N} 帧 = $((TOTAL/N)) kB/帧"

echo "--- 判据① 容器 md5 全同 ---"
UNIQ=$(cat /tmp/memrun_*.txt | awk '/^OK/{print $4}' | sort -u | wc -l)
NOK=$(cat /tmp/memrun_*.txt | grep -c '^OK')
ERR=$(cat /tmp/memrun_*.txt | grep -c '^ERR')
echo "  OK=${NOK}/${N}  ERR=${ERR}  不同 md5 个数=${UNIQ}"
[ "$UNIQ" -eq 1 ] || { echo "!! 同一张图出现了多个 md5"; exit 1; }

echo "--- 判据② 平台期（末块增量 < 首块/3）---"
echo "  首块 +${FIRST_DELTA} kB   末块 +${LAST_DELTA} kB"
if [ "$BLOCKS" -gt 1 ] && [ "$LAST_DELTA" -gt $((FIRST_DELTA/3)) ]; then
    echo "!! 末块还在涨（> 首块的 1/3）⇒ 不是平台期，还可能漏"; exit 1
fi

echo "--- 判据③ 可用内存 ---"
echo "  全程最低未跌破 ${MIN_FREE} MB"
echo
echo "全部通过 ✅  （${N} 帧，RSS ${R0} → ${PREV} kB，可用 ${F0} → $(free_mb) MB）"
