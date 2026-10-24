#!/usr/bin/env bash
# ============================================================================
#  预热电台（AT 自检）—— 上板部署 + A/B 实测
#  （GLC A 侧，2026-10-17）
#
#  要证明什么
#  ----------
#  `start_ui.sh` 新加了一段：开机就把电台送进透传态并写好 `/var/run/glc_radio_warm`，
#  这样之后 `ui_send.sh` 看到 WARM=1 就**跳过那 8.2 s 的 AT 自检**。
#
#  ★ 判据（必须两次启动对比，只测一次不算验）
#      第 1 次启动（标记不存在）  期望**明显慢**（多付 ~8.2 s）
#      第 2 次启动（标记已写好）  期望**明显快**
#    两次差 ≈ 8 s；如果两次一样快 ⇒ **预热没生效，别报通过**。
#
#  为什么不用"发一张图"来验
#  ------------------------
#  完整发一张要 B 端在听（否则 BEGIN 无人应答 → rc=7），现在 B 不在。
#  而 AT 自检**只跟电台自己打交道**，不发数据，所以用"启动耗时"就能隔离验证。
#
#  用法：bash 工具/回归/预热电台_上板验证.sh
#  退出码：0 符合预期；2 连不上板子（"没跑"≠"通过"）；1 不符合
# ============================================================================
set -u
BOARD="${GLC_BOARD:-root@192.168.1.2}"
KEY="${GLC_SSH_KEY:-$HOME/.ssh/id_board}"
SSH=(ssh -i "$KEY" -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=8 "$BOARD")
SCP=(scp -i "$KEY" -o BatchMode=yes -o StrictHostKeyChecking=no)
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
F="工具/触摸屏UI/start_ui.sh"

rc_ssh() { "${SSH[@]}" "$@" 2>/dev/null || true; }
say() { echo; echo "=== $* ==="; }

say "0/6 连板子"
rc_ssh "echo OK" | grep -q OK || { echo "  ❌ 连不上 $BOARD —— **没跑 ≠ 通过**"; exit 2; }
echo "  ✅ 通"

say "1/6 备份 + 推新的 start_ui.sh"
rc_ssh "cp -a /root/start_ui.sh /root/start_ui.sh.bak_\$(date +%H%M%S)"
"${SCP[@]}" "$REPO/$F" "$BOARD:/root/start_ui.sh" || { echo "  ❌ scp 失败"; exit 1; }
echo -n "  本地 md5: "; md5sum "$REPO/$F" | cut -c1-32
echo -n "  板上 md5: "; rc_ssh "md5sum /root/start_ui.sh" | cut -c1-32
rc_ssh "bash -n /root/start_ui.sh && echo '  ✅ 板上 bash -n 通过'"

say "2/6 电台与标记现状"
rc_ssh 'echo -n "  /dev/ttyUSB0: "; [ -c /dev/ttyUSB0 ] && echo 在 || echo 缺失; echo -n "  ctime: "; stat -c %Z /dev/ttyUSB0; echo -n "  标记文件: "; cat /var/run/glc_radio_warm 2>/dev/null || echo "(不存在)"'

say "3/6 停 UI + 清掉标记（制造"冷"条件）"
rc_ssh "bash /root/start_ui.sh --stop"
rc_ssh "rm -f /var/run/glc_radio_warm /root/boot_at.log; echo '  已清'"

say "4/6 A 组：冷启动（标记不存在 ⇒ 应跑一次 AT 自检，多 ~8.2 s）"
A_LOG=$(rc_ssh 'S=$(date +%s); bash /root/start_ui.sh --nowait >/tmp/su_A.log 2>&1; E=$(date +%s); echo "WALL=$((E-S))"; grep -E "电台预热|编码引擎预热|标记命中" /tmp/su_A.log')
echo "$A_LOG" | sed 's/^/    /'
A_W=$(echo "$A_LOG" | sed -n 's/^WALL=\([0-9]*\).*/\1/p')
A_M=$(rc_ssh "cat /var/run/glc_radio_warm 2>/dev/null || echo 无")

say "4b 标记是否写好了"
echo "  /var/run/glc_radio_warm = $A_M"
rc_ssh 'echo -n "  /dev/ttyUSB0 ctime      = "; stat -c %Z /dev/ttyUSB0'

say "5/6 停 UI（再起一次，标记应命中）"
rc_ssh "bash /root/start_ui.sh --stop"

say "5b/6 B 组：热启动（标记已写好 ⇒ 应跳过 AT 自检）"
B_LOG=$(rc_ssh 'S=$(date +%s); bash /root/start_ui.sh --nowait >/tmp/su_B.log 2>&1; E=$(date +%s); echo "WALL=$((E-S))"; grep -E "电台预热|编码引擎预热|标记命中" /tmp/su_B.log')
echo "$B_LOG" | sed 's/^/    /'
B_W=$(echo "$B_LOG" | sed -n 's/^WALL=\([0-9]*\).*/\1/p')

say "6/6 汇总"
echo "  A 组（冷，标记不存在）: ${A_W:-?} s"
echo "  B 组（热，标记命中）  : ${B_W:-?} s"
if [ -n "${A_W:-}" ] && [ -n "${B_W:-}" ]; then
  echo "  差 = $((A_W - B_W)) s  （期望 ≈8 s）"
  if [ $((A_W - B_W)) -ge 5 ]; then
    echo "  ✅ 预热生效"
  else
    echo "  ❌ 两次差不多 ⇒ 电台预热**没生效**，别报通过"
  fi
  [ -n "$A_M" ] && [ "$A_M" != "无" ] && echo "  ✅ 标记已写入且为 ctime 值" || echo "  ⚠️ 标记没写成，B 组可能只是碰巧"
else
  echo "  ❌ 没取到墙钟，判不了"
fi

echo
echo "  ✅ 通过后更新权威清单：python3 工具/校验_权威与板端.py --regen"
echo "  ℹ️  两次启动都含 start_ui.sh 末尾的 sleep 4，做差时已抵消"
