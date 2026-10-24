#!/bin/bash
# ① 正确判断 icraft-serve 是否还在（用中括号技巧避免 pkill 自杀）
# ② 取完整 SUMMARY 计时块
# ③ 拉回 dump 与 PC HostBackend 逐位对拍
set -u
BOARD=192.168.31.72
PASS=fmsh
B=/root/glc/s3p1
LOCAL=/mnt/e/fudanwei/工作区/_board_run/s3p1
PC=/mnt/e/fudanwei/工作区/_verify_npu/zg_int8/run_s3p1/dump/s3_phase1/ftmpSFB
SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=8"
SCP="sshpass -p $PASS scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"

echo "########## 1. icraft-serve 到底还在不在 ##########"
$SSH root@$BOARD 'if pgrep -f "icraft[-]serve" >/dev/null; then echo "  ⚠️ 还在跑: $(pgrep -f "icraft[-]serve" | tr "\n" " ")"; else echo "  ✅ 没有 icraft-serve 进程"; fi; (netstat -tln 2>/dev/null || ss -tln) | grep -q 9981 && echo "  ⚠️ 9981 还在听" || echo "  ✅ 9981 未监听"'

echo
echo "########## 2. 完整计时块（本地 AXI）##########"
$SSH root@$BOARD "grep -A200 'SUMMARY' $B/logs/s3_phase1/*time*.log 2>/dev/null | tail -25" 2>/dev/null | sed 's/^/  /'
echo "  --- 日志目录树 ---"
$SSH root@$BOARD "find $B/logs -type f | sed 's|^|    |'"

echo
echo "########## 3. 拉回 dump ##########"
mkdir -p "$LOCAL/board_dump"
$SCP "root@$BOARD:$B/logs/s3_phase1/ftmpSFB/*.ftmp" "$LOCAL/board_dump/" 2>&1 | grep -v '^$' || true
ls -l "$LOCAL/board_dump/" | sed 's/^/    /'

echo
echo "########## 4. 板上 NPU vs PC HostBackend 逐位对拍 ##########"
for v in 178 182; do
  a="$LOCAL/board_dump/$v.ftmp"
  b="$PC/$v.ftmp"
  if [ -f "$a" ] && [ -f "$b" ]; then
    ma=$(md5sum "$a" | cut -d' ' -f1); mb=$(md5sum "$b" | cut -d' ' -f1)
    if [ "$ma" = "$mb" ]; then echo "    ✅ v_id $v  逐位相同  md5=$ma"
    else echo "    ❌ v_id $v  md5: 板上=$ma PC=$mb"; fi
  else
    echo "    ⚠️ 缺文件  板上=$([ -f "$a" ] && echo 有 || echo 无)  PC=$([ -f "$b" ] && echo 有 || echo 无)"
  fi
done
