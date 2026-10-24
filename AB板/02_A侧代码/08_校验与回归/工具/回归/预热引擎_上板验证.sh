#!/usr/bin/env bash
# ============================================================================
#  预热编码引擎 —— 上板部署 + A/B 实测验证
#  （GLC A 侧，2026-10-17）
#
#  要证明什么
#  ----------
#  `start_ui.sh` 里新加了一段：开机就把 `glcenc_daemon.py` 起起来（`GLC_ENC_IDLE=0` 常驻）。
#  目标是让**第一次**「发送」不再等那 6.6~6.9 s 的引擎载入（NPU 真算只有 346 ms）。
#
#  ★ 必须跑的是 **A/B 两组**，只跑 warm 组不算验：
#      · 冷组（daemon 没起）  期望单张编码 ≈ **8 s 量级**
#      · 热组（预热后）       期望单张编码 ≈ **1.4 s 量级**
#    如果两组差不多 ⇒ 说明预热没生效，**别报"通过"**。
#
#  为什么这么绕（踩过的坑）
#  ----------------------
#  ★ **`--stop` 必须单独一次 ssh**：`start_ui.sh --stop` 内部会 `pkill -f glc_ui.py`，
#    如果同一条远程命令行里还出现 `glc_ui.py` 字面量，远程 shell 会**把自己打死**，连日志都不生成。
#    所以本脚本把 `--stop` 和别的调用**严格分两次**。
#
#  用法（git-bash）
#  ---------------
#      bash 工具/回归/预热引擎_上板验证.sh            # 部署 + A/B + 汇总
#      bash 工具/回归/预热引擎_上板验证.sh --deploy-only
#
#  退出码：0 = A/B 都符合预期；2 = 连不上板子（**"没跑"≠"通过"**）；1 = 有项不符合
# ============================================================================
set -u

BOARD="${GLC_BOARD:-root@192.168.1.2}"
KEY="${GLC_SSH_KEY:-$HOME/.ssh/id_board}"
SSH=(ssh -i "$KEY" -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=8 "$BOARD")
SCP=(scp -i "$KEY" -o BatchMode=yes -o StrictHostKeyChecking=no)
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
F="工具/触摸屏UI/start_ui.sh"
PHOTO="/root/photos/IMG_0001.jpg"
DEPLOY_ONLY=0
[ "${1:-}" = "--deploy-only" ] && DEPLOY_ONLY=1

say() { echo; echo "=== $* ==="; }
rc_ssh() { "${SSH[@]}" "$@" 2>/dev/null || true; }

# 实测一张，输出 `WALL=<秒> MD5=<容器md5>`
# ★ 2026-10-17 修：原来这里是 `grep -oE '[0-9]+\.[0-9]+ s' | head -1`，
#   结果抓到的是 banner 里写死的「单张 ~1.4 s」——**两组都会得到 1.4 s，判据毫无判别力**。
#   现在改成真计时 + 同时取容器 md5（顺带证明产物没变）。
measure_one() {
  rc_ssh "python3 - <<'PY'
import subprocess, time
t = time.time()
r = subprocess.run(['bash','/root/send_image.sh','$PHOTO','--dry','--daemon'],
                   capture_output=True, text=True)
dt = time.time() - t
md5 = ''
for l in r.stdout.splitlines():
    if l.strip().startswith('OK '):
        p = l.split()
        md5 = p[3] if len(p) > 3 else ''
print('WALL=%.2f MD5=%s' % (dt, md5))
PY"
}

say "0/6 连板子"
if ! rc_ssh "echo OK" | grep -q OK; then
  echo "  ❌ 连不上 $BOARD"
  echo "     ⚠️ **没跑 ≠ 通过** —— 自检根本没执行。"
  exit 2
fi
echo "  ✅ 通"

say "1/6 备份板上的 start_ui.sh"
BACKUP="/root/start_ui.sh.bak_$(date +%Y%m%d_%H%M%S)"
rc_ssh "cp -a /root/start_ui.sh '$BACKUP' && ls -l '$BACKUP' | awk '{print \"  备份:\", \$NF, \$5, \"B\"}'"

say "2/6 推新的 start_ui.sh"
"${SCP[@]}" "$REPO/$F" "$BOARD:/root/start_ui.sh" || { echo "  ❌ scp 失败"; exit 1; }
echo -n "  本地 md5: "; md5sum "$REPO/$F" | cut -c1-32
echo -n "  板上 md5: "; rc_ssh "md5sum /root/start_ui.sh" | cut -c1-32
rc_ssh "bash -n /root/start_ui.sh && echo '  ✅ 板上 bash -n 通过'"

[ "$DEPLOY_ONLY" = "1" ] && { echo; echo "  --deploy-only：到此为止"; exit 0; }

# ---------------------------------------------------------------- 冷组
say "3/6 冷组：先确保 daemon 没在跑，再测一张（期望 ≈8 s 量级）"
rc_ssh "python3 /root/glcenc_daemon.py stop 2>/dev/null; sleep 1; python3 /root/glcenc_daemon.py status"
COLD=$(measure_one)
echo "  冷组实测: $COLD"
COLD_W=$(echo "$COLD" | sed -n 's/.*WALL=\([0-9.]*\).*/\1/p')
COLD_M=$(echo "$COLD" | sed -n 's/.*MD5=\([0-9a-f]*\).*/\1/p')
echo "  冷组墙钟 ${COLD_W:-?} s"

# ---------------------------------------------------------------- 起 UI（会预热）
say "4/6 停 UI（★ 单独一次 ssh，避开 pkill 自杀）"
rc_ssh "bash /root/start_ui.sh --stop"

say "4b/6 ★ 把冷组留下的 daemon 也停掉（否则热组测到的还是冷的那个 daemon，等于没验预热）"
rc_ssh "python3 /root/glcenc_daemon.py stop 2>/dev/null; sleep 1; python3 /root/glcenc_daemon.py status"
DM0=$(rc_ssh "pgrep -f glcenc_daemon | tr '\n' ' '")
echo "  停后残留 daemon pid: ${DM0:-（无）}"

say "4c/6 起 UI（新版本会自动预热引擎）"
rc_ssh "bash /root/start_ui.sh --nowait" | tail -16

say "5/6 等引擎就绪 + 确认预热真的生效"
READY=0
for i in $(seq 1 20); do
  OUT=$(rc_ssh "python3 /root/glcenc_daemon.py status" | head -2)
  if echo "$OUT" | grep -q PONG; then
    echo "  ✅ 引擎已就绪（第 $i 次探测）: $OUT"
    READY=1
    break
  fi
  sleep 2
done
[ "$READY" = "0" ] && echo "  ⚠️ 20 次探测都没等到 PONG —— 预热可能没生效，先看 /root/glcenc_daemon.log"

# ---------------------------------------------------------------- 热组
say "6/6 热组：引擎已满载，再测一张（期望明显小于冷组）"
HOT=$(measure_one)
echo "  热组实测: $HOT"
HOT_W=$(echo "$HOT" | sed -n 's/.*WALL=\([0-9.]*\).*/\1/p')
HOT_M=$(echo "$HOT" | sed -n 's/.*MD5=\([0-9a-f]*\).*/\1/p')
echo "  热组墙钟 ${HOT_W:-?} s"

say "汇总"
echo "  冷组（daemon 没起） : ${COLD_W:-?} s   md5 ${COLD_M:-?}"
echo "  热组（预热已载入） : ${HOT_W:-?} s   md5 ${HOT_M:-?}"
echo
if [ -n "${COLD_W:-}" ] && [ -n "${HOT_W:-}" ]; then
  RATIO=$(python3 -c "print('%.1f' % ($COLD_W / max($HOT_W, 0.01)))")
  echo "  加速比 ≈ ${RATIO}×"
  if [ "$COLD_M" = "$HOT_M" ] && [ -n "$COLD_M" ]; then
    echo "  ✅ 两组容器 md5 相同（$COLD_M）⇒ 预热不影响产物"
  else
    echo "  ⚠️ 两组 md5 不同（冷 ${COLD_M} vs 热 ${HOT_M}）⇒ 先查为什么，别急着报通过"
  fi
  if python3 -c "import sys; sys.exit(0 if $COLD_W > 2 * $HOT_W else 1)"; then
    echo "  ✅ 预热生效（冷组 > 2× 热组）"
  else
    echo "  ❌ 两组接近 ⇒ 预热没生效，**不要报通过**"
  fi
else
  echo "  ❌ 没取到墙钟，判不了"
fi

echo
echo "  ✅ 通过之后记得更新权威清单（板上已同步、md5 已变）:"
echo "     python3 工具/校验_权威与板端.py --regen"
