#!/bin/bash
# cam_watch.sh —— 帧流看门狗：断了就自动重启整条链（抓帧 + UI）
#
# 为什么需要它（2026-10-22 用户要求"每次启动相机都能起来"）：
#   · 相机 IP 改不动，只能靠"发现"；相机自己开机要十几秒，板子常常比它先起来；
#   · 相机也可能中途被拔/换线/断电，那时的现象是 **进程还在、帧流停了**（不是崩溃）；
#   · 而 glc_ui 的取流线程一旦 open 失败就退出，**只重启抓帧进程救不回来**，
#     必须连 UI 一起重启。所以这里重启的是"整条链"。
#
# 判据（唯一可信）：/dev/shm/gigecam.meta 的 mtime。超过 STALE 秒没更新 = 帧流死了。
#   —— 不看"进程在不在"，那是 2026-10-20 踩过的坑（帧流冻在第 66 帧但进程活着）。
#
# 节流：两次重启至少间隔 GAP 秒，避免相机反复插拔时把 UI 拖成幻灯片。
STALE=20        # 帧流超过 20 s 没更新就认为死了
GAP=60          # 两次重启的最小间隔
CHECK=10        # 每 10 s 查一次
LOG=/root/cam_watch.log

log() { echo "$(date '+%F %T') $*" >> "$LOG"; }

log "cam_watch start (stale=${STALE}s gap=${GAP}s)"
last=0
while true; do
  now=$(date +%s)
  if [ -f /dev/shm/gigecam.meta ]; then
    m=$(stat -c %Y /dev/shm/gigecam.meta 2>/dev/null || echo 0)
    age=$((now - m))
    if [ "$age" -le "$STALE" ]; then
      sleep "$CHECK"
      continue
    fi
    why="meta 已 ${age}s 没更新"
  else
    why="meta 不存在"
  fi

  if [ $((now - last)) -lt "$GAP" ]; then
    sleep "$CHECK"
    continue
  fi

  log "帧流断了（$why）→ 重启整条链"
  # 只重启链路本身；不从这里杀 cam_watch（它是本进程）
  pkill -f "[g]lc_ui\.py" 2>/dev/null
  pkill -f "[g]ige_grab.py" 2>/dev/null
  sleep 2
  rm -f /dev/shm/gigecam.meta /dev/shm/gigecam.bin
  nohup python3 -u /root/gige_grab.py > /root/gige_grab.log 2>&1 < /dev/null &
  # 等第一帧，最多 20 s
  j=0
  ok=0
  while [ $j -lt 40 ]; do
    [ -f /dev/shm/gigecam.meta ] && { ok=1; break; }
    sleep 0.5
    j=$((j+1))
  done
  if [ "$ok" = "1" ]; then
    log "抓帧恢复：$(cat /dev/shm/gigecam.meta)"
  else
    log "抓帧仍未起来（相机大概不在线），照样起 UI 显示「无信号」"
  fi
  RUN="python3 -u -c \"import sys; sys.argv=['glc_ui.py','--dev','/dev/gigecam','-v','--sleep-after','90','--sleep-blackout','10']; import gige_shim; gige_shim.install(); exec(open('/root/glc_ui.py').read(), {'__name__':'__main__','__file__':'/root/glc_ui.py'})\""
  setsid nohup bash -c "$RUN" > /root/ui_gige.log 2>&1 < /dev/null &
  last=$now
  log "已重启 UI"
  sleep "$CHECK"
done
