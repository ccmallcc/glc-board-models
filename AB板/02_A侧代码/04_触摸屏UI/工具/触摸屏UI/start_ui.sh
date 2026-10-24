#!/bin/bash
# start_ui.sh —— 启动 GLC 触摸屏界面（拍照 + 图库 + 发送）
#
#   bash /root/start_ui.sh              # 启动（后台，日志 /root/ui.log）
#   bash /root/start_ui.sh --fg         # 前台跑，直接看日志
#   bash /root/start_ui.sh --touch      # 启动 + 屏上触摸十字准星（核对坐标映射）
#   bash /root/start_ui.sh --wake       # 应急：强开显示输出
#   bash /root/start_ui.sh --stop       # 停掉
#
# 前置（都是实测验证过的）：
#   · V9 位流在跑：0x400C0084 = 0x20260922（PL rANS 编码器）+ 1024x600 HDMI 显示
#   · 屏：DWE2100 1024x600@59.52Hz，EDID 要 50.25MHz 但 PLLE2 只能给 50.000MHz
#   · 触摸 /dev/input/eventN（1a86:e5e3，ABS_X/Y 0..4096）★ 不要写死 N，重启会变
#   · 摄像头 /dev/video1（0c45:6341，MJPG 640x480）
#   · 电台 /dev/ttyUSB0（1a86:7523，470.110MHz / 19.2kbps 空口 / 115200 串口）
#
# 注意 pkill 的写法：模式写成 "[g]lc_ui" 才不会匹配到执行这条命令的 shell 自己
# （本文件的命令行是 bash /root/start_ui.sh，本来也不含该串，双保险）。
set -u
cd /root

if [ "${1:-}" = "--stop" ]; then
  pkill -f "[g]lc_ui\.py" && echo "已停" || echo "本来就没在跑"
  exit 0
fi

# ---- ★ 等 USB 设备就绪（开机自启时必须）------------------------------------
#   为什么：rc.local 跑的时候（实测开机 ~14 s）USB 不一定枚举完。
#   设备没到就起 UI ⇒ resolve_cam / resolve_touch 找不到 ⇒ 回退到写死的 index
#   ⇒ 屏上「无信号 / 相机未打开」。设备一到位就立刻返回，手动启动时 0 延迟。
if [ "${1:-}" != "--nowait" ]; then
  WAITED=0
  for i in $(seq 1 20); do
    CAM_OK=0; TOUCH_OK=0
    v4l2-ctl --list-devices 2>/dev/null | grep -qi webcam && CAM_OK=1
    grep -qi "usb2iic_ctp" /proc/bus/input/devices 2>/dev/null && TOUCH_OK=1
    [ "$CAM_OK" = "1" ] && [ "$TOUCH_OK" = "1" ] && break
    sleep 1; WAITED=$((WAITED+1))
  done
  [ "$WAITED" -gt 0 ] && echo "  等 USB 设备就绪用了 ${WAITED}s（摄像头=${CAM_OK:-?} 触摸=${TOUCH_OK:-?}）"
fi

# 屏上画触摸十字准星，用来核对"手指按的位置"和"程序认的位置"是否一致
SHOW_TOUCH=""
[ "${1:-}" = "--touch" ] && SHOW_TOUCH="--show-touch"

# ---- 待机（无操作关摄像头 + 黑屏提示）----
#   SLEEP   : 无操作多少秒后进待机。0 = 永不待机。默认 90。
#   BLACKOUT: 待机后**倒计时多少秒再关显示输出**。默认 10。
#             屏上显示「待机中，N 秒后将关闭显示」并每秒刷新，数到 0 就关显示输出。
#             GLC_UI_BLACKOUT=0    -> 不倒数，待机立即关
#             GLC_UI_BLACKOUT=60   -> 倒计时 60 秒
#             GLC_UI_KEEP=1        -> 显示输出永不关，提示一直可见（省电少）
#             无论哪种，触摸都能唤醒。
SLEEP="${GLC_UI_SLEEP:-90}"
BLACKOUT="${GLC_UI_BLACKOUT:-10}"
HINT="待机中，轻触屏幕唤醒"
KEEP="${GLC_UI_KEEP:-0}"
[ "$KEEP" = "1" ] && KEEPF="--sleep-keep-sync" || KEEPF=""

# 应急唤醒：万一显示器在熄屏后没同步回来，用这条把显示输出强开
if [ "${1:-}" = "--wake" ]; then
  busybox devmem 0x40080078 32 0 >/dev/null 2>&1   # ★ 先开同步门控（背光/待机就是它关的）
  busybox devmem 0x400800B4 32 1 >/dev/null 2>&1
  busybox devmem 0x40080018 32 1 >/dev/null 2>&1
  echo "已强开显示输出："
  echo "  0x40080078 = $(busybox devmem 0x40080078 32 2>&1)   (同步门控，应为 0=开)"
  echo "  0x400800B4 = $(busybox devmem 0x400800B4 32 2>&1)   (源选 DDR，应为 1)"
  echo "  0x40080018 = $(busybox devmem 0x40080018 32 2>&1)   (图像使能，应为 1)"
  echo "  0x40080054 = $(busybox devmem 0x40080054 32 2>&1)   (帧地址，应非 0)"
  echo "若屏还是黑的： bash /root/start_ui.sh   （重启界面会重设帧地址并推一帧）"
  exit 0
fi

pkill -f "[g]lc_ui\.py" 2>/dev/null
pkill -f "[c]am_to_hdmi" 2>/dev/null       # 两个程序抢同一个帧缓冲寄存器，不能同时跑
sleep 1

# 环境自检
echo "=== 环境自检 ==="
printf "  位流指纹(0x400C0084) : %s   (要 0x20260922 = PL rANS 在位)\n" \
       "$(busybox devmem 0x400C0084 32 2>/dev/null || echo '读不到')"
# ★ 这里原来写的是 `[ -e /dev/input/event0 ] && echo OK` —— 会撒谎：
#   重启后 event0 被摄像头（它自带 kbd 句柄）抢走，触摸屏漂到 event1，
#   但 event0 仍然"存在" ⇒ 自检报 OK 而实际点哪儿都没反应。
#   改成按设备名解析，并且用 EVIOCGABS 真问一下是不是触摸屏。
TOUCH_DEV="$(python3 - <<'PYEOF'
txt = open("/proc/bus/input/devices", encoding="utf-8", errors="replace").read()
for block in txt.split("\n\n"):
    name = handlers = ""
    for ln in block.splitlines():
        if ln.startswith("N: Name="):
            name = ln.split("=", 1)[1].strip().strip('"')
        elif ln.startswith("H: Handlers="):
            handlers = ln.split("=", 1)[1]
    low = name.lower()
    if name and handlers and ("usb2iic_ctp" in low or "wch.cn" in low):
        for tok in handlers.split():
            if tok.startswith("event") and tok[5:].isdigit():
                print("/dev/input/" + tok); raise SystemExit
print("/dev/input/event0")
PYEOF
)"
printf "  触摸 %-20s: %s   (按设备名解析；写死 eventN 会在重启后错)\n" "$TOUCH_DEV" \
       "$([ -e "$TOUCH_DEV" ] && echo OK || echo '缺失')"
# 摄像头：用**和 resolve_cam 完全相同的判据**（Card type 含 webcam + Device Caps 段里
# 有 Video Capture 且无 Metadata Capture）。不能图省事写 `head -1`：
# webcam 有采集/metadata 两个同名节点，枚举顺序一变就会指到 metadata 上。
CAM_DEV=""
for d in $(v4l2-ctl --list-devices 2>/dev/null | grep -o '/dev/video[0-9]*' | sort -u); do
    info="$(v4l2-ctl -d "$d" --info 2>/dev/null || true)"
    card="$(printf '%s\n' "$info" | sed -n 's/^[[:space:]]*Card type[[:space:]]*:[[:space:]]*//p' | head -1)"
    caps="$(printf '%s\n' "$info" | sed -n '/Device Caps/,$p')"
    printf '%s' "$card" | grep -qiE 'webcam|camera' || continue
    printf '%s' "$caps" | grep -q 'Video Capture'     || continue
    printf '%s' "$caps" | grep -q 'Metadata Capture' && continue
    CAM_DEV="$d"; break
done
printf "  摄像头 %-19s: %s   (同 resolve_cam 判据；实测重启后 videoN 会变号)\n" \
       "${CAM_DEV:-（没找到）}" "$([ -n "$CAM_DEV" ] && echo OK || echo '缺失')"
printf "  中文字体 /root/ui_font.ttf: %s\n" \
       "$([ -f /root/ui_font.ttf ] && stat -c%s /root/ui_font.ttf || echo '缺失(见 make_ui_font.py)')"
printf "  电台 /dev/ttyUSB0    : %s\n" \
       "$([ -c /dev/ttyUSB0 ] && echo '有 -> 发送会真的发射' || echo '无 -> 发送只做 GLC 编码')"
printf "  照片目录             : %s 张\n" "$(ls /root/photos 2>/dev/null | wc -l)"
if [ "$SLEEP" = "0" ]; then
  printf "  待机                 : 关闭（不待机）\n"
elif [ "$KEEP" = "1" ]; then
  printf "  待机                 : 无操作 %ss 后关摄像头 + 黑屏提示「%s」，触摸唤醒\n" "$SLEEP" "$HINT"
  printf "  显示输出             : **永不关**（提示一直可见，省电少）\n"
elif [ "$BLACKOUT" = "0" ]; then
  printf "  待机                 : 无操作 %ss 后关摄像头 + **立即关显示输出**（真熄屏），触摸唤醒\n" "$SLEEP"
  printf "  显示输出             : 立即关（屏全黑最省电；提示只在断电前一瞬闪一下）\n"
else
  printf "  待机                 : 无操作 %ss 后关摄像头，屏上倒计时「待机中，N 秒后将关闭显示」\n" "$SLEEP"
  printf "  显示输出             : 倒数 %ss 后关（触摸随时唤醒）\n" "$BLACKOUT"
fi
printf "  同步门控(0x40080078) : %s   (1=同步已拉掉、显示器待机/背光灭；0=正常)\n" \
       "$(busybox devmem 0x40080078 32 2>/dev/null || echo '读不到')"

# ---------------------------------------------------------------- 预热编码引擎
# 为什么：常驻引擎一次性载入 5 个子图要 **6.6~6.9 s**，而其中 **NPU 真算只有 346 ms**
#        （`icraft-run` 跑 S1：进程墙钟 6.66 s ⇒ 95% 花在"把模型装进去"）。
#        不预热的话，用户按**第一次**「发送」要干等这 7 秒 —— 实测首张 **7.46 s**、
#        之后每张 **0.72 s**。开机就把引擎起好 ⇒ 首张也走"已载入"路径。
#
# 安全前提（都验过源文件，不是想当然）：
#   ① `glcenc_daemon.py start` 自带幂等保护（`glcenc_daemon.py:403-405`：
#      `if ping(): print('已经在跑了，不重复启动')`）⇒ 之后 `send_image.sh --daemon`
#      会**复用**这个 daemon，**不会起第二个**去抢 NPU socket。
#   ② `daemonize()` 是双 fork 且父进程立刻 `sys.exit(0)`（`:345-350`）⇒ **不拖慢 UI 启动**。
#   ③ `GLC_ENC_IDLE=0` = **空闲永不自动退出**（默认 300 s），整场演示都用同一个已载入引擎。
#   ④ 任何失败都只打一行，**绝不能让 UI 起不来** ⇒ `|| true`。
#
# ⚠️ 副作用（知道就行）：`--stop` **不会**顺手停 daemon（故意的，重启 UI 时能立刻用），
#    要停请单独跑 `python3 /root/glcenc_daemon.py stop`。
if [ -f /root/glcenc_daemon.py ]; then
  GLC_ENC_IDLE=0 python3 /root/glcenc_daemon.py start >/dev/null 2>&1 || true
  printf "  编码引擎预热         : 已后台启动（约 8 s 可用；GLC_ENC_IDLE=0 常驻不退出）\n"
  printf "                          查状态: python3 /root/glcenc_daemon.py status\n"
else
  printf "  编码引擎预热         : 跳过（无 /root/glcenc_daemon.py）\n"
fi

# ---------------------------------------------------------------- 预热电台（AT 自检）
# 为什么：`ui_send.sh` 第一次发送时要先花 **8.2 s** 做一次 AT 自检把电台送进透传态
#        （`drain 2.0 + '+++' 1.5 + 3×AT 查询 1.0 + 'AT+EXIT=1' 1.2 + sleep 0.5`）。
#        做完它会把 ctime 写进 `/var/run/glc_radio_warm`，之后靠这个标记跳过。
#        **`/var/run` 是 tmpfs ⇒ 每次重启标记必丢** ⇒ 不预热的话，
#        上电后第一张就要多等 8.2 s（实测首张 19.9 s 里 8.23 s 是它）。
#
# ★★ 为什么这里**同步**等它做完，而不是像引擎那样丢后台：
#    `ui_send.sh:84-118` 在 WARM=0 时也会自己起一个 `A_send_session.py --at-only`。
#    如果两边**同时**开着 `/dev/ttyUSB0`，会互抢字节（`ui_send.sh:102` 的注释原话），
#    表现成 BEGIN 收不到 ACK / rc=7。同步做掉就没有这个竞态。
#
# ✅ 只在**本次开机第一次**付这 8.2 s：标记在 tmpfs 里，同一次开机内重启 UI 会命中而跳过。
# ★★ 2026-10-17 收盘改：这段**挪到拉起 UI 之后**再跑（原来在 UI 之前，白挡 8.2 s 黑屏）。
#    顺序依据（本次开机日志）：daemon 与 AT 同时开始、都在 +33 s 结束，但 UI 是
#    **等 AT 做完才被拉起**的 ⇒ 出画面被推迟 8.2 s。引擎是后台的、现在 AT 也后台了，
#    画面反而先出来；电台预热在用户还没摸到「发送」按钮时就做完了。
#    竞态防护：做 AT 时写 /var/run/glc_at_warming，`ui_send.sh` 见到会等它（最多 20 s）。
at_warm() {
  [ -c /dev/ttyUSB0 ] && [ -f /root/A_send_session.py ] || {
    printf "  电台预热             : 跳过（无 /dev/ttyUSB0 或 无 A_send_session.py）\n"; return 0; }
  local RADY_NOW WARMST
  RADY_NOW=$(stat -c %Z /dev/ttyUSB0 2>/dev/null || echo '?')
  WARMST=/var/run/glc_radio_warm
  if [ -f "$WARMST" ] && [ "$(cat "$WARMST" 2>/dev/null)" = "$RADY_NOW" ]; then
    printf "  电台预热             : 标记命中（已在透传态），跳过 AT 自检\n"; return 0
  fi
  : > /var/run/glc_at_warming          # ★ 告诉 ui_send.sh：我在占电台，等我
  printf "  电台预热             : 后台做 AT 自检（~8.2 s，**不挡画面**）…\n"
  if python3 -u /root/A_send_session.py --at-only >/root/boot_at.log 2>&1; then
    printf '%s\n' "$RADY_NOW" > "$WARMST"
    printf "                         ✅ 成功，已记标记 ctime=%s\n" "$RADY_NOW"
  else
    printf "                         ⚠️ 失败（rc=$?），不影响 UI；下次发送时会自己重做\n"
    tail -3 /root/boot_at.log 2>/dev/null | sed 's/^/                           /'
  fi
  rm -f /var/run/glc_at_warming
}

if [ "${1:-}" = "--fg" ]; then
  at_warm &            # --fg 会把本 shell exec 掉，所以必须先把 AT 丢后台
  exec python3 -u /root/glc_ui.py --dev auto -v \
       --sleep-after "$SLEEP" --sleep-blackout "$BLACKOUT" $KEEPF $SHOW_TOUCH
fi

# -v：把每一次真实触摸（按下坐标/命中热区/是否被判为点按）记进 /root/ui.log，
#     方便核对"手指点的地方"和"程序认的地方"是不是同一个位置。量很小。
setsid nohup python3 -u /root/glc_ui.py --dev auto -v \
    --sleep-after "$SLEEP" --sleep-blackout "$BLACKOUT" $KEEPF $SHOW_TOUCH \
    > /root/ui.log 2>&1 < /dev/null &
sleep 4
echo
echo "=== 已启动 (pid $(pgrep -f '[g]lc_ui\.py' | head -1))，日志 /root/ui.log ==="
grep -vE "Corrupt JPEG|\[info\]" /root/ui.log | tail -8
echo
at_warm &            # ★ 画面已经出来了，电台预热在后台补上（约 8 s）
echo "  电台预热             : 已在后台继续（期间按「发送」会自动等它）"
echo
echo "  屏上应该看到：左边「曝光 EV」面板 + 中间实时预览 + 底部 图库/快门/发送最新"
echo "  停： bash /root/start_ui.sh --stop"
echo "  截图：kill -USR1 \$(pgrep -f '[g]lc_ui\.py' | head -1)  -> /root/ui_dump.png"
