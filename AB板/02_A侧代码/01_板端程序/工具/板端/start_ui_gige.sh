#!/bin/bash
# start_ui_gige.sh —— 网口相机（MV-CE013-50GC）→ 显示界面
#
# 与 USB 链路并存：不动 /root/start_ui.sh、不动 glc_ui.py。
# 原理：后台 gige_grab.py 连续抓帧到 /dev/shm，gige_shim.py 拦截 cv2.VideoCapture，
#       UI 用 --dev /dev/gigecam（glc_ui.py 对 /dev/ 开头的参数直接采用，不探测）。
#
# 用法：
#   bash /root/start_ui_gige.sh          # 后台起（日志 /root/ui_gige.log）
#   bash /root/start_ui_gige.sh --fg     # 前台跑（调试用）
#   bash /root/start_ui_gige.sh --stop   # 全停（含抓帧与看门狗）
#
# ★ 2026-10-22 晚（用户要求"每次启动相机都能起来"）：
#   相机 IP 改不动（见 88 号文 §八），所以**不靠 IP**，改成：
#     ① 抓帧进程最多重试 3 次 × 20 s —— 相机自己开机要十几秒，板子常常比它先起来；
#     ② 起完再拉一个 cam_watch.sh 看门狗，帧流断了 >20 s 就自动重启整条链；
#     ③ 相机彻底不在也能起 UI（显示「无信号」），不会全黑。
set -u
cd /root

SLEEP="${GLC_UI_SLEEP:-90}"
BLACKOUT="${GLC_UI_BLACKOUT:-10}"

if [ "${1:-}" = "--stop" ]; then
  pkill -f "[c]am_watch.sh" 2>/dev/null && echo "看门狗已停" || echo "看门狗未在跑"
  pkill -f "[g]lc_ui\.py" 2>/dev/null && echo "UI 已停" || echo "UI 未在跑"
  pkill -f "[g]ige_grab.py" 2>/dev/null && echo "抓帧已停" || echo "抓帧未在跑"
  exit 0
fi

# 停掉旧的（用 [g] 规避 pkill 匹配到本脚本自身命令行）
pkill -f "[g]lc_ui\.py" 2>/dev/null
pkill -f "[g]ige_grab.py" 2>/dev/null
# ★ 2026-10-23：这里原来固定 sleep 1。pkill 之后进程几十毫秒就死了，
#   等 1 s 是纯浪费（两次进这个函数就浪费 2 s）。改成 0.3 s。
sleep 0.3

# ── 0) 等 eth0 出现，并保证地址都在 ───────────────────────────
i=0
while [ $i -lt 40 ]; do
  ip link show eth0 >/dev/null 2>&1 && break
  sleep 1
  i=$((i+1))
done
ip link set eth0 up 2>/dev/null || true
# 板子地址：2026-10-22 从 192.168.1.2 改成 .10（原来的 .2 撞了相机，见 88 号文）
ip addr add 192.168.1.10/24 dev eth0 2>/dev/null || true
# 链路本地 /16：相机若掉回 169.254.x（DHCP 失败时的默认行为），这条是唯一的通路
ip addr add 169.254.1.1/16 dev eth0 2>/dev/null || true

# ── 1) 起抓帧：最多 3 次 × 20 s（相机开机慢，一次不成不代表坏了）──
rm -f /dev/shm/gigecam.meta /dev/shm/gigecam.bin
OK=0
for attempt in 1 2 3; do
  pkill -f "[g]ige_grab.py" 2>/dev/null
  sleep 0.3
  rm -f /dev/shm/gigecam.meta /dev/shm/gigecam.bin
  # ★ 2026-10-23：相机 ROI 从 256×256 改成 **512×512**（大图模式要 4 块 256 拼 512）。
  #   小图模式 = 从这 512 里**中心裁 256**，视场与原来的 256 ROI 完全相同。
  #   gige_grab.py 支持 --w/--h，并会自动把 OffsetX/Y 居中到 1280×960 传感器。
  python3 /root/boot_splash.py --pct 45 --text "连接相机" >/dev/null 2>&1 || true
  nohup python3 -u /root/gige_grab.py --w 512 --h 512 > /root/gige_grab.log 2>&1 < /dev/null &
  echo "抓帧第 $attempt 次启动，等第一帧（最多 20 s）..."
  j=0
  while [ $j -lt 40 ]; do
    if [ -f /dev/shm/gigecam.meta ]; then OK=1; break; fi
    sleep 0.5
    j=$((j+1))
  done
  if [ "$OK" = "1" ]; then
    echo "第一帧就绪：$(cat /dev/shm/gigecam.meta)"
    break
  fi
  echo "  第 $attempt 次没拿到帧（相机可能还没起来），5 s 后重试"
  sleep 5
done

if [ "$OK" != "1" ]; then
  # ★ 相机不在线时**不能退出**：一退出就整屏全黑、连"无信号"都没有。
  #   glc_ui.py 自己有「无信号 / 相机未打开」分支（Cam.open() 失败只停抓帧线程）。
  echo "!! 三次都没抓到帧（相机不在线？看 /root/gige_grab.log）—— 仍启动 UI，屏上会显示「无信号」"
fi

# ── 2) 用 shim 跑原版 UI（相机没通也照常起，会画「无信号」）──────
python3 /root/boot_splash.py --pct 90 --text "启动界面" >/dev/null 2>&1 || true
# ★ 2026-10-23：**界面先出来，引擎在后台热起来**。
#   背景：开机为了快（~22 s 出界面），开机链并**不加载 NPU 引擎**，
#   于是第一张发送要多付 ~6.6 s 冷载入 + ~8.2 s 电台 AT 自检 ≈ 15~20 s。
#   这里在启动器起来 **20 s 后**用一张固定的 256 小图悄悄编码一次（--dry，不发电台），
#   让 daemon 把 5 个子图载入完毕；之后用户第一次按发送只需付 AT 自检。
#   安全性：daemon 有 STARTLOCK(/var/run/glcenc_start.pid)，重复启动会被挡；
#   预热失败 || true，绝不挡任何正常流程；图片放 /root 下（不在 photos 里，不进图库）。
# 引擎预热：由 warm_engine.sh 负责"等 UI 起来 +3 s 再热"，不再用固定 sleep 20。
# 旧做法 warm 完成于 boot+41.3 s（实测），用户在 20~41 s 之间发送就吃冷载入。
[ -x /root/warm_engine.sh ] && nohup bash /root/warm_engine.sh > /dev/null 2>&1 < /dev/null &
# 电台 AT 预热（独立脚本，见工具/板端/at_warm.sh 里的说明）
[ -x /root/at_warm.sh ] && nohup bash /root/at_warm.sh > /root/at_warm.log 2>&1 < /dev/null &
RUN="python3 -u -c \"import sys; sys.argv=['glc_ui.py','--dev','/dev/gigecam','-v','--sleep-after','$SLEEP','--sleep-blackout','$BLACKOUT']; import gige_shim; gige_shim.install(); exec(open('/root/glc_ui.py').read(), {'__name__':'__main__','__file__':'/root/glc_ui.py'})\""

if [ "${1:-}" = "--fg" ]; then
  echo "前台启动 UI（网口相机）"
  eval "$RUN"
else
  setsid nohup bash -c "$RUN" > /root/ui_gige.log 2>&1 < /dev/null &
  sleep 4
  echo "UI 已后台启动，日志 /root/ui_gige.log"
  tail -3 /root/ui_gige.log 2>/dev/null
fi

# ── 3) 看门狗：帧流断了自动重启整条链（每次启动只拉一个）──────
if ! pgrep -f "[c]am_watch.sh" >/dev/null 2>&1; then
  setsid nohup bash /root/cam_watch.sh > /root/cam_watch.log 2>&1 < /dev/null &
  echo "看门狗已起（cam_watch.sh）"
else
  echo "看门狗已在跑"
fi
