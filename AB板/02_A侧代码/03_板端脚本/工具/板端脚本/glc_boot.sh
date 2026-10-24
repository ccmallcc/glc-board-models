#!/bin/bash
# =============================================================================
#  glc_boot.sh —— 开机早期编排：位流 → tmpfs → 触摸屏 UI
#  （2026-10-17 新增，由 systemd 的 glc-boot.service 在 sysinit 阶段调，**不等网络**）
#
#  为什么要从 rc.local 里搬出来
#  ----------------------------
#  实测（dmesg / systemd-analyze）：
#    · USB 三件套 2.7~4.0 s 就枚举完了；sysinit.target 在 6.55 s 到达
#    · 但 rc.local 排在 network-online.target 之后 ⇒ 到 **15 s** 才起 UI
#    · 位流 5.98 MB 只要 ~1 s，原来却到 13.07 s 才开始写（前面压着 ifconfig/dhclient）
#  ⇒ 这三件事跟网络毫无关系，搬进 sysinit 阶段后：位流 ~7 s 好、UI ~8 s 起。
#
#  顺序不能换：位流（UI 要查位流指纹）→ tmpfs（引擎中间张量要走 /dev/shm）→ UI。
#  任何一步失败都不许拖累后面（`|| true`），否则屏就永远黑着。
# =============================================================================
LOG=/var/log/glc_ui_boot.log
exec >>"$LOG" 2>&1
echo
echo "=== glc-boot 开始 uptime=$(cut -d. -f1 /proc/uptime)s ==="

# ① 位流（UI 起来要读 0x400C0084 的指纹）
[ -x /root/glc/load_bitstream.sh ] && bash /root/glc/load_bitstream.sh || true

# ② tmpfs 软链（引擎中间张量要写 /dev/shm；/tmp 也挂 tmpfs）
[ -f /root/speed_setup.sh ] && bash /root/speed_setup.sh || true

# ③ UI
# ★★ 2026-10-20 重启实测的大坑：本单元 Before=rc-local.service，所以这里**跑在
#    rc.local 之前**。而 rc.local 里有 ifconfig eth0 down / hw ether / up（改 MAC）——
#    抓帧进程刚连上相机，4 秒后网口被 reset，**帧流就永久冻在那一帧**
#    （实测 seq 停在 66: 66/15fps ≈ 4.4 s，正好是 rc.local 的时刻）。
#    屏上表现是"相机没启动/画面不动"，而进程其实都活着。
#    ⇒ 不能在 rc.local 之前开抓帧。这里后台起一个"等 rc-local 跑完再启动"的包装。
#    （不能在本脚本里直接 wait：rc.local 要等本单元结束才跑，会死锁。）
[ -x /root/start_ui_gige.sh ] && setsid nohup bash -c 'U(){ cut -d. -f1 /proc/uptime; }; echo "[wrap] start uptime=$(U)"; i=0; while [ $i -lt 90 ]; do systemctl is-active --quiet rc-local && break; sleep 1; i=$((i+1)); done; echo "[wrap] rc-local active uptime=$(U) waited=${i}s"; j=0; while [ $j -lt 30 ]; do ip -4 addr show eth0 2>/dev/null | grep -q 192.168.1.10 && break; sleep 0.1; j=$((j+1)); done; echo \"[wrap] eth0 ready uptime=$(U) j=$j\"; echo "[wrap] exec launcher uptime=$(U)"; exec /root/start_ui_gige.sh' > /root/ui_boot_wrap.log 2>&1 < /dev/null &

echo "=== glc-boot 结束 uptime=$(cut -d. -f1 /proc/uptime)s ==="
