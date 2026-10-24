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
#  send_image.sh  ——  A 板：把图片编码成 GLC 容器并用电台发出去
#
#  一条命令：
#      bash /root/send_image.sh /root/photo/p1.jpg
#      bash /root/send_image.sh /root/photo/*.jpg          # 一次会话发多张
#      bash /root/send_image.sh /root/photo/p1.jpg --repeat 10
#      bash /root/send_image.sh --dry /root/photo/p1.jpg   # 只编码，不发
#      bash /root/send_image.sh /root/photos_glc/p1.glc    # 直接发现成容器
#
#  编码三种模式（默认 ①）：
#      ① --daemon         常驻守护进程：**单张 ~1.4 s**（预处理也在进程内做）。⚠️ 见文首说明
#                          空闲 300 s 自己退出，不会长期占着 NPU。
#      ② --batch（默认）  一次性批处理：首张付一次引擎载入（冷 ~13 s / 热 ~6.7 s），
#                          之后每张 ~0.71 s（PL rANS）/ ~0.89 s（CPU 打包）。跑完就退。
#      ③ --single         老的"每张一个进程"单张链，每张 10~17 s。排障用。
#
#  ★ 三种模式产出的容器**逐字节一致**（已实测 p1/p2/p3/p4/p5/p6 全对）。
#
#  其它选项原样转给 A_send_session.py：
#      --mode fit|crop|squash   预处理方式（默认 fit）
#      --repeat N               同一批连发 N 轮
#      --dry                    只编码 + 打印，不占电台
#      --no-lens / --attempts N / --begin-attempts N ...
#
#  产物：/root/send_work/<时间戳>/  每张一个 .glc + 输入张量 + 日志
#  日志：/root/send_work/last.log（最新一次完整输出）
# =============================================================================
set -u

GLC_DIR=/root/glc
WORK_ROOT=/root/send_work
BATCH_OUT=$GLC_DIR/batch_out_cpu
ENC_IN=$GLC_DIR/run/s1/in0.ftmp
DAE_IN=$WORK_ROOT/_daemon_in      # 守护进程模式：直接把原图交给它，不用中转
MODE=fit
REPEAT=1
DRY=0
# ★ 默认用一次性批处理，不用常驻守护进程。
#   实测：今天板子两次整机掉电都发生在 NPU 持续工作之后（第二次是守护进程在跑时）。
#   原因未确证（很可能是供电，见 45 号文档 §10），所以默认不再常驻占 NPU。
#   想用最快的守护进程，显式加 --daemon。
ENC_MODE=batch         # batch | daemon | single
TAG=""
PASSTHRU=""
IMAGES=""
BIG=0                 # 0=小图(单张 256) 1=大图(512 切 4 块 256，一个会话 N=4)

while [ $# -gt 0 ]; do
  case "$1" in
    --mode)            MODE="$2"; shift 2 ;;
    --mode=*)          MODE="${1#*=}"; shift ;;
    --repeat)          REPEAT="$2"; shift 2 ;;
    --repeat=*)        REPEAT="${1#*=}"; shift ;;
    --tag)             TAG="$2"; shift 2 ;;
    --tag=*)           TAG="${1#*=}"; shift ;;
    --big)             BIG=1; shift ;;
    --small)           BIG=0; shift ;;
    --dry)             DRY=1; shift ;;
    --single)          ENC_MODE=single; shift ;;
    --batch)           ENC_MODE=batch; shift ;;
    --daemon)          ENC_MODE=daemon; shift ;;
    --help|-h)         sed -n '2,32p' "$0"; exit 0 ;;
    --*)
      case " --begin-wait --begin-attempts --wait --gap --attempts --max-consec-fail --retry-rounds --rate " in
        *" $1 "*) PASSTHRU="$PASSTHRU $1 $2"; shift 2 ;;
        *)        PASSTHRU="$PASSTHRU $1"; shift ;;
      esac
      ;;
    *)                 IMAGES="$IMAGES $1"; shift ;;
  esac
done

case "$PASSTHRU" in
  *--begin-attempts*) : ;;
  *) PASSTHRU="$PASSTHRU --begin-attempts 5" ;;
esac

if [ -z "$IMAGES" ]; then
  echo "用法: bash /root/send_image.sh <图片或.glc> [更多...] [--mode fit] [--repeat N] [--dry] [--daemon|--batch|--single] [--big|--small]"
  exit 2
fi

# ---------------------------------------------------------------- 大图模式
# 一个「大图」= 512×512 切 4 块 256×256，**一个会话 N=4、MODE=1**，顺序 TL,TR,BL,BR。
# 多张大图 ⇒ **逐张开会话**（每张一个 N=4），不合并成一个 N=4k —— B 端判据最简单：
#   "MODE=1 时本次会话必定正好 4 帧"。
if [ "$BIG" = "1" ]; then
  n_img=$(echo $IMAGES | wc -w)
  if [ "$n_img" -gt 1 ]; then
    echo "  大图模式：$n_img 张 -> 逐张处理（每张一个 N=4 会话）"
    rc_all=0
    for im in $IMAGES; do
      echo "  ---- 大图 $im ----"
      DRY_FLAG=""
      [ "$DRY" = "1" ] && DRY_FLAG="--dry"
      bash "$0" "$im" --big --mode "$MODE" --repeat "$REPEAT" $DRY_FLAG --$ENC_MODE $PASSTHRU || rc_all=$?
    done
    exit $rc_all
  fi
  TILE_DIR="$WORK_ROOT/tiles_$$"
  rm -rf "$TILE_DIR"; mkdir -p "$TILE_DIR"
  python3 /root/tile_split.py --in $IMAGES --outdir "$TILE_DIR" --big
  if [ $? -ne 0 ]; then echo "!! 分块失败"; exit 5; fi
  IMAGES="$(ls "$TILE_DIR"/*.jpg | sort | tr '
' ' ')"
  echo "  大图模式：已切成 4 块 -> $IMAGES"
  case "$PASSTHRU" in
    *--mode*) : ;;
    *) PASSTHRU="$PASSTHRU --mode 1" ;;
  esac
else
  # 小图：MODE=0。显式写上，免得 B 端拿到一个"没写 MODE"的旧包。
  case "$PASSTHRU" in
    *--mode*) : ;;
    *) PASSTHRU="$PASSTHRU --mode 0" ;;
  esac
fi

TS=$(date +%Y%m%d_%H%M%S)
[ -n "$TAG" ] && TS="${TS}_${TAG}"
WORK="$WORK_ROOT/$TS"
mkdir -p "$WORK_ROOT"

# 防并发：编码链用固定路径（run/s1/in0.ftmp、pack/full_img0、batch_out_cpu）
LOCK=/var/run/glc_send.lock
if [ -e "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
  echo "!! 已经有一次发图在跑（pid $(cat "$LOCK")）。编码链用固定路径，请等它结束。"
  exit 5
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT INT TERM

ln -sfn "$WORK" "$WORK_ROOT/latest" 2>/dev/null
mkdir -p "$WORK" "$DAE_IN"

exec > >(tee -a "$WORK_ROOT/last.log") 2>&1

echo "############################################################################"
echo "# GLC 电台发图   $(date '+%F %T')"
echo "# 工作目录: $WORK"
echo "############################################################################"

# ---- 2026-10-17：可选分阶段计时（GLC_SEND_TIME=1）。用 bash 内建 EPOCHREALTIME，
#      **不起子进程**（`date +%s%N` 每次 fork ~5 ms，会把这台板子的账算花）。
TS0=${EPOCHREALTIME//[.,]/}
tsay() {
  [ "${GLC_SEND_TIME:-0}" = "1" ] || return 0
  local t=${EPOCHREALTIME//[.,]/}
  printf '        [TIME] %-16s %6d ms\n' "$1" $(( t / 1000 - TS0 / 1000 ))
}
tsay "启动(含 bash/日志 tee)"

# ---------------------------------------------------------------- 环境自检
echo
echo "=== [0/3] 环境自检 ==="
if [ ! -c "$GLC_RADIO_DEV" ]; then
  if [ "${GLC_ALLOW_NO_RADIO:-0}" = "1" ]; then
    echo "  ⚠ 没有 "$GLC_RADIO_DEV"（电台）。GLC_ALLOW_NO_RADIO=1 ⇒ 只编码不发射（自动 --dry）"
    echo "  实际 USB 设备:"
    lsusb 2>/dev/null | head -5 | sed 's/^/      /'
    DRY=1
  else
    echo "!! 找不到 "$GLC_RADIO_DEV"（电台）。lsusb 应该能看到 1a86:7523"
    lsusb 2>/dev/null | head -5
    exit 3
  fi
else
  echo "  电台设备  : "$GLC_RADIO_DEV" OK"
fi
echo -n "  位流指纹  : "; busybox devmem 0x400C0084 32 2>/dev/null || echo "(读不到)"
echo -n "  内存      : "; free -m | awk 'NR==2{printf "总 %s MB / 可用 %s MB\n",$2,$7}'
echo -n "  空闲磁盘  : "; df -h / | awk 'NR==2{print $4}'
[ -f /root/glcenc_client.py ] || { [ "$ENC_MODE" = "daemon" ] && { echo "  !! 缺 glcenc_client.py，回落批处理"; ENC_MODE=batch; }; }
[ -f "$GLC_DIR/glc_batch_cpu.py" ] && [ -f "$GLC_DIR/glc_batch_rsd.py" ] || { [ "$ENC_MODE" = "batch" ] && { echo "  !! 缺 glc_batch_cpu.py，回落单张链"; ENC_MODE=single; }; }
case "$ENC_MODE" in
  daemon) echo "  编码方式  : 常驻守护进程（单张 ~1.4 s）" ;;
  batch)  echo "  编码方式  : 常驻批处理（每张 ~0.60 s(PL) / ~0.89 s(CPU) + 一次引擎载入 ~6.7 s）" ;;
  single) echo "  编码方式  : 单张链（每张 10~17 s）" ;;
esac

# ---------------------------------------------------------------- 1. 收集
tsay "环境自检"
echo
echo "=== [1/3] 收集输入 ==="
: > "$WORK/.imglist"     # stem<TAB>原图
i=0
for src in $IMAGES; do
  i=$((i+1))
  if [ ! -f "$src" ]; then echo "  [$i] !! 找不到 $src —— 跳过"; continue; fi
  base=$(basename "$src")
  stem="${base%.*}"
  case "$base" in
    *.glc)
      cp -f "$src" "$WORK/$stem.glc"
      echo "  [$i] $base  (已是容器)  $(stat -c%s "$WORK/$stem.glc") B"
      ;;
    *)
      # 复制到守护进程的输入区（避免原图被挪走/改动）
      cp -f "$src" "$DAE_IN/$stem.${base##*.}" 2>/dev/null || cp -f "$src" "$DAE_IN/$stem.png"
      printf '%s\t%s\n' "$stem" "$DAE_IN/$stem.${base##*.}" >> "$WORK/.imglist"
      echo "  [$i] $base  ->  待编码"
      ;;
  esac
done
NIMG=$(grep -c . "$WORK/.imglist" 2>/dev/null || echo 0)

imgs_of () { while IFS="$(printf '\t')" read -r n p; do [ -n "${n:-}" ] && printf '%s\n' "$n"; done < "$WORK/.imglist"; }
src_of  () { grep -P "^$1\t" "$WORK/.imglist" | head -1 | cut -f2; }

tsay "收集输入"
# ---------------------------------------------------------------- 2. 编码
echo
echo "=== [2/3] 编码 ==="
FALLBACK=0

if [ "$NIMG" -gt 0 ]; then
  case "$ENC_MODE" in
    # ============================================== 守护进程
    daemon)
      echo "  --- 常驻守护进程（预处理 + NPU 都在进程内）---"
      # ★★ 2026-10-17 二次提速：**不再先 PING**。
      #   原来这里先起一个 python 做 PING，只为判断"daemon 在不在"——
      #   垫片实测：`glcenc_client.py PING` 整个 = **136 ms**（其中 65 ms 是 python 启动地板，
      #   `python3 -c pass` 就是 65 ms）。而这一次发送的编码只有 593+287=880 ms，
      #   所以那 136 ms 是纯开销。
      #   现在：**直接把活干下去**。`glcenc_client.py` 连不上会返回退出码 1（NO_DAEMON），
      #   只有那种情况才启动 daemon 再重试。正常路径（daemon 常驻）少一个进程。
      #   退出码约定（见 glcenc_client.py 文件头）：0=OK/PONG/BYE，1=服务没起，2=服务返回 ERR。
      ARGS=""
      for n in $(imgs_of); do ARGS="$ARGS $n=$(src_of "$n")"; done
      # shellcheck disable=SC2086
      OUT=$(python3 /root/glcenc_client.py ENCBATCH "$WORK" $ARGS 2>/dev/null); RC=$?
      if [ "$RC" -eq 1 ]; then
        echo "        守护进程没起，启动它（引擎后台载入，约 8~15 s）…"
        GLC_ENC_IDLE=300 python3 /root/glcenc_daemon.py start
        for k in $(seq 1 90); do
          OUT=$(python3 /root/glcenc_client.py ENCBATCH "$WORK" $ARGS 2>/dev/null); RC=$?
          [ "$RC" -eq 1 ] || break
          sleep 1
        done
      fi
      if [ "$RC" -ne 1 ] && printf '%s' "$OUT" | grep -q "^OK"; then
        echo "$OUT" | sed 's/^/        /'
      else
        echo "        !! 守护进程起不来 / 编码失败，回落批处理"
        FALLBACK=1
        ENC_MODE=batch
      fi
      ;;

    # ============================================== 单张链 / 批处理
    *)
      echo "  --- 预处理（enc_image.py）---"
      : > "$WORK/.manlist"
      for n in $(imgs_of); do
        s=$(src_of "$n")
        if python3 /root/enc_image.py "$s" --mode "$MODE" --out "$ENC_IN" \
              --png "$WORK/${n}_crop.png" 2>&1 \
              | grep -vE 'DeprecationWarning|im = im.resize|^$' | sed 's/^/        /'; then
          if [ -f "$ENC_IN" ]; then
            cp -f "$ENC_IN" "$WORK/${n}.in.ftmp"
            printf '%s\t%s\n' "$n" "$WORK/${n}.in.ftmp" >> "$WORK/.manlist"
          fi
        fi
      done

      if [ "$ENC_MODE" = "batch" ]; then
        # ★ 按位流指纹自动选最快的编码路径（实测 2026-09-22，256x256）：
        #     指纹 = 0x20260922（我们的 rans_top）⇒ glc_batch_rsd.py  PL rANS   0.60 s/张
        #     否则                              ⇒ glc_batch_cpu.py  A53 CPU    0.894 s/张
        #   两者容器逐字节一致（p1~p7 的 md5 全对）。
        #   前置 speed_setup.sh：把操作数目录与 /tmp 搬进 tmpfs（单独值 ~0.3 s/张）。
        sh /root/speed_setup.sh >/dev/null 2>&1
        FP=$(busybox devmem 0x400C0084 32 2>/dev/null || echo "?")
        if [ "$FP" = "0x20260922" ]; then
          BATCH_SCRIPT=glc_batch_rsd.py; BATCH_LABEL="PL rANS（FPGA）"
          BATCH_OUT=$GLC_DIR/batch_out          # rsd 版写这里
        else
          BATCH_SCRIPT=glc_batch_cpu.py; BATCH_LABEL="A53 CPU 打包（指纹 $FP）"
          BATCH_OUT=$GLC_DIR/batch_out_cpu      # cpu 版写这里
        fi
        echo "  --- 常驻批处理：$BATCH_LABEL ---"
        for n in $(imgs_of); do rm -f "$BATCH_OUT/$n.glc"; done
        ARGS=()
        while IFS="$(printf '\t')" read -r n p; do [ -n "${n:-}" ] && ARGS+=("$n=$p"); done < "$WORK/.manlist"
        S=$(date +%s)
        ( cd "$GLC_DIR" && GLC_RSD_RESET=each python3 -u "$BATCH_SCRIPT" "${ARGS[@]}" ) \
            > "$WORK/batch.log" 2>&1
        BRC=$?
        E=$(date +%s)
        tr -d '\033' < "$WORK/batch.log" | sed 's/\[2K//g' \
          | grep -E '就绪|单张墙钟|每张墙钟|首张|合计墙钟|PL rANS 实测|^###   ' | sed 's/^/        /'
        echo "        批处理 rc=$BRC  总墙钟 $((E-S)) s"
        # ★ 只拷这次点名要的那几张（用 *.glc 通配会把上次剩的旧容器也拷进来，会多发图）
        for n in $(imgs_of); do
          [ -f "$BATCH_OUT/$n.glc" ] && cp -f "$BATCH_OUT/$n.glc" "$WORK/$n.glc"
        done
      else
        echo "  --- 单张链（每张 10~17 s）---"
        while IFS="$(printf '\t')" read -r n p; do
          [ -n "${n:-}" ] || continue
          cp -f "$p" "$ENC_IN"
          T0=$(date +%s)
          ( cd "$GLC_DIR" && python3 glc_board_full.py --sample 0 ) > "$WORK/enc_$n.log" 2>&1
          R=$?
          case "$R" in
            0|3) sh "$GLC_DIR/pack_full.sh" 0 >> "$WORK/enc_$n.log" 2>&1
                 cp -f "$GLC_DIR/pack/full_img0_cpu.glc" "$WORK/$n.glc" 2>/dev/null ;;
            *)   echo "        $n !! 编码 rc=$R（见 enc_$n.log）" ;;
          esac
          echo "        $n rc=$R  $(( $(date +%s) - T0 )) s"
        done < "$WORK/.manlist"
      fi
      ;;
  esac

  # 兜底：还没产出的，用单张链补
  MISS=""
  for n in $(imgs_of); do [ -f "$WORK/$n.glc" ] || MISS="$MISS $n"; done
  if [ -n "$MISS" ]; then
    echo "        !! 还缺:$MISS —— 用单张链补"
    for n in $MISS; do
      s=$(src_of "$n")
      [ -n "$s" ] || continue
      python3 /root/enc_image.py "$s" --mode "$MODE" --out "$ENC_IN" >/dev/null 2>&1
      T0=$(date +%s)
      ( cd "$GLC_DIR" && python3 glc_board_full.py --sample 0 ) > "$WORK/enc_$n.log" 2>&1
      R=$?
      case "$R" in
        0|3) sh "$GLC_DIR/pack_full.sh" 0 >> "$WORK/enc_$n.log" 2>&1
             cp -f "$GLC_DIR/pack/full_img0_cpu.glc" "$WORK/$n.glc" 2>/dev/null ;;
      esac
      echo "        $n rc=$R  $(( $(date +%s) - T0 )) s"
    done
  fi
fi

tsay "编码(含 daemon 往返)"
# ---------------------------------------------------------------- 汇总
echo
GLCS=""
OK=0
for g in "$WORK"/*.glc; do
  [ -e "$g" ] || continue
  sz=$(stat -c%s "$g")
  md=$(md5sum "$g" | cut -d' ' -f1)
  echo "  => $(basename "$g")  ${sz} B  md5=${md}"
  echo "     空口净时间 ≈ $(awk "BEGIN{printf \"%.2f\", $sz*8/19200}") s @19.2 kbps"
  GLCS="$GLCS $g"
  OK=$((OK+1))
done
if [ -z "$GLCS" ]; then echo; echo "!! 一张都没编码成功，退出"; exit 4; fi

if [ "$REPEAT" -gt 1 ]; then
  ORIG="$GLCS"; GLCS=""
  r=0
  while [ "$r" -lt "$REPEAT" ]; do
    for g in $ORIG; do
      cp -f "$g" "$WORK/r$(printf '%02d' $r)_$(basename "$g")"
      GLCS="$GLCS $WORK/r$(printf '%02d' $r)_$(basename "$g")"
    done
    r=$((r+1))
  done
  echo "  --repeat $REPEAT -> 共 $(echo $GLCS | wc -w) 个容器待发"
fi

N=$(echo $GLCS | wc -w)
TOT=0; for g in $GLCS; do TOT=$((TOT + $(stat -c%s "$g"))); done
echo
echo "  编码完成：$OK 张图 -> $N 个容器，合计 $TOT B"
echo "  纯空口时间 ≈ $(awk "BEGIN{printf \"%.1f\", $TOT*8/19200}") s（协议开销另计）"

if [ "$DRY" = "1" ]; then
  echo
  if [ "${GLC_ALLOW_NO_RADIO:-0}" = "1" ] && [ ! -c "$GLC_RADIO_DEV" ]; then
    echo "=== 无电台：只编码，不发。容器在 $WORK ==="
  else
    echo "=== --dry 指定，不发。容器在 $WORK ==="
  fi
  tsay "汇总(dry 路径)"
  echo "SEND_IMAGE_DONE dry=1 n=$N"
  exit 0
fi

# ---------------------------------------------------------------- 3. 发送
echo
echo "=== [3/3] 电台发送（会话模式，一次发完 $N 张）==="
echo "  ⚠️ 请先确认 B 端已经在监听。等不到会在约 30 s 后放弃。"
echo
python3 /root/A_send_session.py $GLCS $PASSTHRU
RC=$?

echo
echo "=== 本次产物（把这 4 列发给 B 核对）==="
printf "  %-4s  %-30s %5s  %s\n" "序号" "文件名" "字节" "md5"
i=0
for g in $GLCS; do
  i=$((i+1))
  printf "  %-4d  %-30s %5d  %s\n" "$i" "$(basename "$g")" "$(stat -c%s "$g")" "$(md5sum "$g" | cut -d' ' -f1)"
done
echo
echo "  目录: $WORK"
echo "  日志: $WORK_ROOT/last.log"
tsay "电台发送"
echo "SEND_IMAGE_DONE rc=$RC n=$N"
exit $RC
