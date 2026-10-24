#!/usr/bin/env bash
# ============================================================================
#  发 B 之前必须跑的自检 —— 协议 / 常驻接收
#  （GLC A 侧，2026-10-15）
#
#  为什么要有它
#  ------------
#  我们**两次**把"想当然"当成事实发给 B：
#    · `40` 号文 §4 写了 `radio_rx_session.py -n 7` —— 那个脚本**根本没有 `-n` 参数**
#      （收几张是从 `SESSION_BEGIN` 的 N 字段读的）。`79`/`80` 号文又照抄了一遍。
#    · 给 B 的参考实现里 `rx%d.glc` 用**会话内序号**当文件名 —— 单次运行看不出来，
#      一改成常驻（N 个 `N=1` 会话）就**互相覆盖，日志还全绿**。
#  ⇒ 结论：**发出去之前，先在板子上把协议跑一遍**；不跑就等于没验。
#
#  跑什么（两个都在板子上跑，都用 PTY 假电台，**不需要真电台**）
#  ------------------------------------------------------------------
#   ① `test_session_proto.py`  协议本身：帧格式 / 分片 / 噪声 / 坏校验和 / N=63 / RETRY / ABORT
#   ② `test_rx_serve_pty.py`   常驻接收：**3 个会话 × 1 张**能不能全收下、会不会互相覆盖
#                              ★ 它自带一组"**必须能失败**"的对照（旧的一次性脚本应报 无应答）
#
#  为什么必须在板子上
#  ------------------
#  两个测试都 `import pty`（`test_session_proto.py:16`）—— **Windows 没有 `pty`**，只能在 Linux 跑。
#  用板子的好处是**顺带证明"在真实板端 Python 上也能跑"**，而不是只在开发机上能跑。
#
#  用法（git-bash）
#  ---------------
#      bash 工具/回归/发给B前的自检.sh
#      bash 工具/回归/发给B前的自检.sh --keep     # 跑完不删板上的临时目录
#
#  环境变量（都可省）
#  ------------------
#      GLC_BOARD     默认 root@192.168.1.2
#      GLC_SSH_KEY   默认 ~/.ssh/id_board
#      GLC_REMOTE    默认 /root/glc_selftest
#
#  退出码：0 = 两项都通过；非 0 = 有几项没通过（看末尾汇总）
# ============================================================================
set -u

BOARD="${GLC_BOARD:-root@192.168.1.2}"
KEY="${GLC_SSH_KEY:-$HOME/.ssh/id_board}"
REMOTE="${GLC_REMOTE:-/root/glc_selftest}"
KEEP=0
[ "${1:-}" = "--keep" ] && KEEP=1

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
WIRE="$REPO/工具/无线"

SSH=(ssh -i "$KEY" -o BatchMode=yes -o StrictHostKeyChecking=no "$BOARD")
SCP=(scp -i "$KEY" -o BatchMode=yes -o StrictHostKeyChecking=no)

# 被测文件清单（**连同它们的 md5 一起打出来** —— 只说"通过"不说"哪些字节通过"是不算验的）
FILES=(
  "工具/无线/A_send_session.py"
  "工具/无线/radio_rx_session.py"
  "工具/无线/radio_rx_serve.py"
  "工具/无线/test_session_proto.py"
  "工具/无线/test_rx_serve_pty.py"
)

echo "=============================================================="
echo " 发 B 前自检（协议 / 常驻接收）"
echo "   仓库   $REPO"
echo "   板子   $BOARD"
echo "   远端   $REMOTE"
echo "=============================================================="

# ---------------------------------------------------------------- ① 本地文件
echo
echo "[1/4] 检查本地文件与 md5"
MISSING=0
for f in "${FILES[@]}"; do
  if [ ! -f "$REPO/$f" ]; then
    echo "  ❌ 缺 $f"
    MISSING=1
    continue
  fi
  printf '  %s  %s\n' "$(md5sum "$REPO/$f" | cut -c1-32)" "$f"
done
if [ "$MISSING" != "0" ]; then
  echo
  echo "❌ 有文件缺失，自检无法进行。"
  exit 2
fi

# ---------------------------------------------------------------- ② 推送
echo
echo "[2/4] 推送到板子 $REMOTE"
"${SSH[@]}" "mkdir -p '$REMOTE'" 2>/dev/null || {
  echo "  ❌ 连不上板子（$BOARD）。"
  echo "     ⚠️ **连不上 ≠ 通过** —— 自检没跑就是没跑，别当成绿。"
  exit 2
}
"${SCP[@]}" "${FILES[@]/#/$REPO/}" "$BOARD:$REMOTE/" >/dev/null 2>&1 || {
  echo "  ❌ scp 失败"
  exit 2
}
echo "  ✅ 已推送 ${#FILES[@]} 个文件"

# 板上再核一次 md5：证明**跑的就是刚推的那几个字节**（不是板上的旧副本）
echo "  板上 md5 复核："
"${SSH[@]}" "cd '$REMOTE' && md5sum A_send_session.py radio_rx_session.py radio_rx_serve.py test_session_proto.py test_rx_serve_pty.py" 2>/dev/null \
  | sed 's/^/    /'

# ---------------------------------------------------------------- ③ 跑测试
# ★ 注意：`run_one` **不能把结果 echo 到 stdout 再 $(...) 抓** ——
#   那样会把整段测试输出都抓进变量里。改成写全局 LAST_RC。
LAST_RC=99
run_one() {   # $1=序号 $2=脚本 $3=标题
  echo
  echo "[$1] $3"
  echo "--------------------------------------------------------------"
  "${SSH[@]}" "cd '$REMOTE' && python3 $2; echo __RC=\$?" 2>/dev/null \
    | tee "/tmp/glc_selftest_$2.log" | tail -n 40
  LAST_RC=$(grep -o '__RC=[0-9]*' "/tmp/glc_selftest_$2.log" | tail -1 | cut -d= -f2)
  LAST_RC=${LAST_RC:-99}
  echo "--------------------------------------------------------------"
  echo "  ⇒ $2 退出码 $LAST_RC      （完整日志 /tmp/glc_selftest_$2.log）"
}

run_one "3/4" "test_session_proto.py" "① 协议自测（帧格式 / 分片 / 噪声 / 坏校验和 / N=63 / RETRY / ABORT）"
RC1=$LAST_RC
run_one "4/4" "test_rx_serve_pty.py" "② 常驻接收自测（3 个会话 × 1 张；含'必须能失败'的对照）"
RC2=$LAST_RC

# ---------------------------------------------------------------- ④ 汇总
echo
echo "=============================================================="
echo " 汇总"
echo "=============================================================="
ok=0
if [ "$RC1" = "0" ]; then echo "  ✅ ① test_session_proto.py     PASS"; else echo "  ❌ ① test_session_proto.py     FAIL (rc=$RC1)"; ok=1; fi
if [ "$RC2" = "0" ]; then echo "  ✅ ② test_rx_serve_pty.py      PASS（对照那组也符合预期）"; else echo "  ❌ ② test_rx_serve_pty.py      FAIL (rc=$RC2)"; ok=1; fi

if [ "$ok" = "0" ]; then
  echo
  echo "  ⇒ 可以发给 B。"
  # ★ 这一行必须用单引号：反引号在双引号里会被当命令替换执行掉
  echo '     ⚠️ 发之前再确认一遍：文档里引用的**参数名 / 文件名 / 数字**都是回源码核过的，'
  echo '        不是照抄我们上一份文档（40 号文那个 -n 就是这么错的）。'
else
  echo
  echo "  ⇒ ⛔ **先别发。** 上面有 FAIL —— 发出去 B 会照着错的做。"
fi

if [ "$KEEP" = "0" ]; then
  "${SSH[@]}" "rm -rf '$REMOTE'" 2>/dev/null
else
  echo "  （--keep：板上 $REMOTE 保留）"
fi

echo "=============================================================="
exit "$ok"
