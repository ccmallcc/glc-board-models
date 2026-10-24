#!/bin/bash

# ---- GLC 2026-10-15: 电台设备按 USB id 解析，**不写死 ttyUSBn** ----
#   为什么：USB 串口编号来自**枚举顺序**；再插一个 USB 串口设备，电台就可能变 ttyUSB1。
#   摄像头/触摸屏早改成按名字解析了（见 71 号文），这是最后一个写死的地方。
#   A_send_session.py 第 44 行已经支持 GLC_RADIO_DEV ⇒ 这里只要 export。
if [ -z "${GLC_RADIO_DEV:-}" ]; then
    GLC_RADIO_DEV="$(bash /root/glc/radio_dev.sh 2>/dev/null || true)"
    [ -n "$GLC_RADIO_DEV" ] || GLC_RADIO_DEV=/dev/ttyUSB0
    export GLC_RADIO_DEV
fi

# =============================================================================
#  ui_send.sh —— 触摸屏 UI 的发送封装（v2：NPU 常驻 + 电台状态缓存 + 并行）
#
#  一次发送原本 19.9 s，其中编码只占 0.65 s、**PL rANS 只占 0.0029 s**。
#  时间全在"准备工作"上。本脚本把这两块都干掉：
#
#  ① NPU 引擎常驻（send_image.sh --daemon）
#        batch 模式每按一次都冷载入 5 个子图 = 6.99 s
#        daemon 只付一次，之后单张 **1.6 s**（实测）
#        容器逐字节一致：IMG_0015 → 875fb89a83fd8b780bfaeb08eea6520e（两种模式同值）
#
#  ② 电台 AT 自检只做一次
#        A_send_session.py 每次开机都 drain(2.0)+at('+++',1.5)+3条查询各等1.0+EXIT(1.2)
#        = 8.2 s，而电台其实每次都是**第一次 ~0.02 s 就答对**。
#        发完它会把电台留在**透传模式**，而透传模式是保持的 ⇒ 下一次可以直接 --at-done。
#        用 /var/run/glc_radio_warm 记状态，内容 = /dev/ttyUSB0 的 ctime
#        （重新插拔会让 ctime 变，标记自动失效）。
#
#  ③ 首次仍然并行：AT 自检 ‖ 编码，避免白白串行等待。
#
#  ★ 自愈设计（不靠"假设电台一直好"）：
#      · rc=3/6（AT 参数不符 / 没进透传）      -> 立刻清标记
#      · rc=7（BEGIN 没被确认）连续 2 次        -> 清标记（可能电台被复位了，
#        但也可能只是 B 端没在听，所以给一次容忍）
#      · /dev/ttyUSB0 的 ctime 变了            -> 标记自动失效
#
#  ⚠️ 风险（用户已知情并拍板）：常驻占 NPU。45 号文档记过板子两次整机掉电都发生在
#     NPU 持续工作之后，原因未确证（很可能是供电）。daemon 空闲 GLC_UI_ENC_IDLE 秒
#     自己退出（默认 300，和项目原默认一致），不会长期占着。
#
#  用法：bash /root/ui_send.sh <图片>
#  末行固定：UI_SEND_DONE rc=N stage=... 
# =============================================================================
set -u

IMG="${1:-}"

# ---------------------------------------------------------------- 大图/小图
# 大图 = 512×512 切 4 块 256×256，**一个会话 N=4、MODE=1**（顺序 TL,TR,BL,BR）。
# 小图 = 中心裁 256×256，**一个会话 N=1、MODE=0**。
# 两种都可显式用 --big 指定，也可由 UI 通过环境变量 GLC_UI_BIG=1 传下来。
BIG="${GLC_UI_BIG:-0}"
for a in "$@"; do [ "$a" = "--big" ] && BIG=1; done
[ "$BIG" = "1" ] && BIGFLAG="--big" || BIGFLAG="--small"
MODEFLAG="0"; [ "$BIG" = "1" ] && MODEFLAG="1"
[ -n "$IMG" ] || { echo "用法: bash /root/ui_send.sh <图片>"; echo "UI_SEND_DONE rc=2 stage=arg"; exit 2; }
[ -f "$IMG" ] || { echo "!! 找不到 $IMG"; echo "UI_SEND_DONE rc=2 stage=arg"; exit 2; }

STATE=/var/run/glc_radio_warm      # 内容 = "$GLC_RADIO_DEV" 的 ctime；匹配才认为电台在透传态
FAILF=/var/run/glc_send_failcnt    # BEGIN 连续失败计数
IDLE="${GLC_UI_ENC_IDLE:-300}"
# BEGIN 重试次数：每次 (等 6 s + 隔 4 s) = 10 s。
# 项目默认 5 次 = B 端不在时要干等 50 s —— 对触摸界面太长了。
# 实测 B 端在场时**每次都第 1 次就答**（0.22 s），所以 3 次（30 s）足够。
ATTEMPTS="${GLC_UI_BEGIN_ATTEMPTS:-3}"

# ---------------------------------------------------------------- 没有电台
if [ ! -c "$GLC_RADIO_DEV" ]; then
  echo "[UI] 没有 "$GLC_RADIO_DEV" ⇒ 只编码，不发射"
  GLC_ALLOW_NO_RADIO=1 bash /root/send_image.sh "$IMG" --dry --daemon $BIGFLAG
  RC=$?
  echo "UI_SEND_DONE rc=$RC stage=encode_only n=$([ $RC -eq 0 ] && echo 1 || echo 0) radio=0"
  exit $RC
fi

# ★ 2026-10-17：开机时 start_ui.sh 会在**后台**做一次 AT 自检（约 8.2 s，已不挡画面）。
#   它占着电台时我们先等它 —— 两边同时开 /dev/ttyUSB0 会互抢字节，
#   表现成 BEGIN 收不到 ACK / rc=7。
if [ -f /var/run/glc_at_warming ]; then
  echo "[UI] 开机 AT 预热还在跑，等它（最多 20 s）…"
  i=0
  while [ -f /var/run/glc_at_warming ] && [ "$i" -lt 40 ]; do sleep 0.5; i=$((i+1)); done
  echo "[UI] 等完了（${i} x 0.5 s）"
fi

RADY=$(stat -c %Z "$GLC_RADIO_DEV" 2>/dev/null || echo "?")
WARM=0
if [ -f "$STATE" ] && [ "$(cat "$STATE" 2>/dev/null)" = "$RADY" ]; then WARM=1; fi

T0=$(date +%s)
echo "[UI] ============ 发送 $IMG ============"
if [ "$WARM" = "1" ]; then
  echo "[UI] 电台状态缓存命中（ctime=$RADY）⇒ 跳过 AT 自检（省 ~8.2 s）"
  echo "[UI] STAGE=READY"
else
  echo "[UI] 电台缓存未命中 ⇒ 需要 AT 自检（与编码并行跑）"
fi

# ---------------------------------------------------------------- ① 并行起跑
AT_PID=""
if [ "$WARM" != "1" ]; then
  rm -f /root/ui_at.log
  python3 -u /root/A_send_session.py --at-only > /root/ui_at.log 2>&1 &
  AT_PID=$!
  echo "[UI] ① AT 自检后台跑，pid=$AT_PID"
  echo "[UI] STAGE=AT"
fi

# ---------------------------------------------------------------- ② 编码
echo "[UI] ② GLC 编码（--daemon，引擎常驻；空闲 ${IDLE}s 自退）"
echo "[UI] STAGE=ENC"
GLC_ENC_IDLE="$IDLE" bash /root/send_image.sh "$IMG" --dry --daemon $BIGFLAG
RC_ENC=$?
T_ENC=$(( $(date +%s) - T0 ))
echo "[UI]    编码 rc=$RC_ENC ｜ 累计已用 ${T_ENC} s"

# ---------------------------------------------------------------- ③ 等自检
if [ -n "$AT_PID" ]; then
  echo "[UI] ③ 等 AT 自检收尾（必须等：两边同时开 "$GLC_RADIO_DEV" 会互抢字节，"
  echo "[UI]    而且自检期间电台在命令模式，二进制帧会被当 AT 乱码吃掉）"
  echo "[UI] STAGE=ATWAIT"
  wait $AT_PID
  RC_AT=$?
  T1=$(date +%s)
  echo "[UI]    AT 自检 rc=$RC_AT ｜ 并行段墙钟 $((T1 - T0)) s"
  sed 's/^/[AT] /' /root/ui_at.log | tail -4
  if [ $RC_AT -ne 0 ]; then
    rm -f "$STATE"
    echo "[UI] !! 电台自检没过，不发"
    echo "UI_SEND_DONE rc=$RC_AT stage=at n=0"
    exit $RC_AT
  fi
  echo "$RADY" > "$STATE"
  echo "[UI]    电台已进透传，记下标记 ⇒ 下次跳过自检"
fi

[ $RC_ENC -eq 0 ] || { echo "[UI] !! 编码失败"; echo "UI_SEND_DONE rc=$RC_ENC stage=encode n=0"; exit $RC_ENC; }


# ---------------------------------------------------------------- ④ 发送
if [ "$BIG" = "1" ]; then
  # 大图：send_image.sh 把 4 块分别编码成 000.glc..003.glc（顺序 = TL,TR,BL,BR）
  GLCS=""
  for k in 000 001 002 003; do
    g="/root/send_work/latest/$k.glc"
    [ -f "$g" ] || { echo "[UI] !! 缺大图分块容器 $g"; echo "UI_SEND_DONE rc=9 stage=container n=0 mode=big"; exit 9; }
    GLCS="$GLCS $g"
  done
  GLC="$GLCS"
  echo "[UI] 大图：4 个分块容器 $(for g in $GLCS; do stat -c%s "$g"; done | tr '
' ' ')"
else
  STEM=$(basename "$IMG"); STEM="${STEM%.*}"
  GLC="/root/send_work/latest/$STEM.glc"
  GLCS="$GLC"
  [ -f "$GLC" ] || { echo "[UI] !! 找不到容器 $GLC"; echo "UI_SEND_DONE rc=9 stage=container n=0"; exit 9; }
fi

# ---------------------------------------------------------------- ③.5 容器过大 ⇒ 拒发
# ★ 2026-10-23 实测（A 侧/B 端都在线时逐档试出来的）：
#   **单帧上限 ≈ 1279 B**：1240/1260 通，1280 不通，1300/1600/3200 全不通。
#   猜测是电台/B 端 1280 字节的接收缓冲，超过就截断 ⇒ 校验失败 ⇒ 永远等不到 ACK。
#   后果很恶劣：一张 10 KB 的容器会让 A 端把 `--attempts 8` 用满（8 × 10 s = 80 s），
#   再叠加补发轮和 UI 轮询，实测总墙钟 **237 s** 才放弃。
# 而正常画面根本用不到这么多：实测真照片容器 **308 / 344 / 352 / 360 / 368 B**，
#   离上限还有 3~4 倍余量。所以**超过 1200 B 基本可以判定这一帧是异常帧**
#   （实测那张 10,016 B 的容器，头部参数与正常容器**逐字节相同**、都是 256×256，
#     只有第 4 条流从 44 B 爆到 9,740 B ⇒ 输入是高熵噪声/坏帧，不是"图太复杂"）。
MAXGLC="${GLC_MAX_CONTAINER:-1200}"

# ★ 2026-10-23：**先重编一次，再判定异常**。
#   证据：那张 10,016 B 的容器，源图是 /root/photos/IMG_0019.jpg（640×480），
#   今天用同一张图重编**两次都是 328 B**（确定性）⇒ 10 KB 不是内容问题，
#   而是那一次编码读到了未初始化/半写的缓冲（尾部是 FE FF 重复填充）。
#   所以遇到超大容器先**重编一次**：绝大多数情况下重编就正常，用户完全无感；
#   只有重编后仍然超大，才认定是异常帧、拒发（rc=12）。
_reencode_once() {
  echo "[UI] 容器过大 ⇒ 先重编一次（这类异常多数是编码时读到垃圾缓冲，重编即恢复）"
  GLC_ENC_IDLE="$IDLE" bash /root/send_image.sh "$IMG" --dry --daemon $BIGFLAG > /root/ui_reenc.log 2>&1
  RC_RE=$?
  echo "[UI]   重编 rc=$RC_RE"
  return $RC_RE
}

CHECK_FAIL=0
for g in $GLCS; do
  sz=$(stat -c%s "$g" 2>/dev/null || echo 0)
  [ "$sz" -gt "$MAXGLC" ] && CHECK_FAIL=1
done
if [ "$CHECK_FAIL" = "1" ]; then
  _reencode_once || true
  # 重编后重新定位容器（大图是 4 个，小图 1 个）
  if [ "$BIG" = "1" ]; then
    GLCS=""
    for k in 000 001 002 003; do
      g="/root/send_work/latest/$k.glc"
      [ -f "$g" ] && GLCS="$GLCS $g"
    done
    GLC="$GLCS"
  fi
  CHECK_FAIL=0
  for g in $GLCS; do
    sz=$(stat -c%s "$g" 2>/dev/null || echo 0)
    if [ "$sz" -gt "$MAXGLC" ]; then
      CHECK_FAIL=1
      BADSZ="$sz"
    fi
  done
fi

if [ "$CHECK_FAIL" = "1" ]; then
  echo "[UI] !! 重编后容器仍是 ${BADSZ:-?} B（>${MAXGLC} B），判定异常帧，拒发"
  echo "[UI]    （正常画面 300~400 B；单帧上限实测 ≈1279 B，硬发要等 ~80 s 无 ACK）"
  echo "UI_SEND_DONE rc=12 stage=size n=0 size=${BADSZ:-0}"
  exit 12
fi

# ★ 2026-10-23：带上"原图尺寸与字节数"，让 B 端能显示压缩比（体现 GLC 的优势）。
#   容器头里没有分辨率，B 只能看到"收到几百字节"，算不出原始大小。
#   这里取的是**发送的这张源图**（大图时为那张 512 原图，不是分块）。
ORIG=$(python3 -c 'import os,sys
from PIL import Image
p=sys.argv[1]
im=Image.open(p)
print("%dx%d:%d" % (im.size[0], im.size[1], os.path.getsize(p)))' "$IMG" 2>/dev/null)
if [ -n "$ORIG" ]; then
  echo "[UI]    原图 ${ORIG%%:*}，${ORIG##*:} B（会写进 SESSION_BEGIN，供 B 端显示压缩比）"
else
  echo "[UI]    （取不到原图尺寸，BEGIN 不携带 ORIG）"
  ORIGARG=""
fi
[ -n "$ORIG" ] && ORIGARG="--orig $ORIG" || ORIGARG=""

echo "[UI] ④ 正式发送（--at-done，BEGIN 最多试 ${ATTEMPTS} 次）—— 已用 $(( $(date +%s) - T0 )) s"
echo "[UI] STAGE=SEND"
python3 -u /root/A_send_session.py $GLCS --at-done --begin-attempts "$ATTEMPTS" --mode "$MODEFLAG" $ORIGARG
RC=$?
T2=$(date +%s)

# ---------------------------------------------------------------- 自愈
if [ $RC -eq 0 ]; then
  rm -f "$FAILF"
elif [ $RC -eq 7 ]; then
  # BEGIN 没被确认：可能只是 B 端没在听，给一次容忍；连续两次才怀疑电台被复位
  N=$(cat "$FAILF" 2>/dev/null || echo 0); N=$((N + 1)); echo "$N" > "$FAILF"
  if [ "$N" -ge 2 ]; then
    rm -f "$STATE" "$FAILF"
    echo "[UI] BEGIN 连续 $N 次没人确认 ⇒ 清掉电台缓存标记，下次重做 AT 自检"
  else
    echo "[UI] BEGIN 第 $N 次没人确认（暂不清标记；再失败一次就重做 AT 自检）"
  fi
else
  rm -f "$FAILF"
  case "$RC" in
    3|6)
      rm -f "$STATE"
      echo "[UI] 电台异常 rc=$RC（AT 参数不符 / 没进透传）⇒ 清标记，下次重做自检"
      ;;
  esac
fi

echo "[UI] 全部墙钟 $((T2 - T0)) s"
echo "UI_SEND_DONE rc=$RC stage=send n=$([ "$BIG" = "1" ] && echo 4 || echo 1) radio=1 mode=$MODEFLAG glc=$GLC warm=$WARM"
exit $RC
