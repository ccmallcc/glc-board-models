#!/bin/bash
# backup_board.sh —— 板端全量代码备份（一条命令产出可离线恢复的 tar.gz + 清单）
#
# 目标：硬件故障时，拿这个包 + 一份 md5 清单就能把板子恢复到"能跑"的状态。
#
# 覆盖范围：
#   /root/*.py /root/*.sh /root/*.json /root/*.txt
#   （**不收集 .log** —— 日志大且无恢复价值；Q9-#9 指出旧注释写错，已订正）
#   /etc/rc.local
#   只收我们自建的两个：cam-lla.service、getty@ttyPS0.service.d/（不写通配）
#   /etc/systemd/system/getty@ttyPS0.service.d/
#   /etc/netplan/（尽管理论上没用）
#   /etc/network/interfaces*
#   crontab -l
# 不覆盖：模型文件、/opt/MVS（体积大且可重装，单独记 md5）
#
# 用法：bash /root/backup_board.sh
# 产物：/root/board_backup_<YYYYmmdd_HHMM>.tar.gz  + 同名 .md5.txt 清单

set -u
TS=$(date +%Y%m%d_%H%M)
OUT=/root/board_backup_$TS
STAGE=/tmp/board_backup_$TS
rm -rf "$STAGE"; mkdir -p "$STAGE"/{root,etc,systemd}

echo "=== 1) 收集 /root 代码 ==="
for f in /root/*.py /root/*.sh /root/*.json /root/*.txt; do
    [ -f "$f" ] || continue
    cp -p "$f" "$STAGE/root/" 2>/dev/null
done

echo "=== 2) 收集 /etc 关键文件 ==="
[ -f /etc/rc.local ] && cp -p /etc/rc.local "$STAGE/etc/"
[ -d /etc/netplan ] && cp -rp /etc/netplan "$STAGE/etc/" 2>/dev/null
cp -p /etc/network/interfaces "$STAGE/etc/" 2>/dev/null

echo "=== 3) 收集自建的 systemd 单元 ==="
for u in cam-lla.service; do
    [ -f "/etc/systemd/system/$u" ] && cp -p "/etc/systemd/system/$u" "$STAGE/systemd/"
done
[ -d /etc/systemd/system/getty@ttyPS0.service.d ] && \
    cp -rp /etc/systemd/system/getty@ttyPS0.service.d "$STAGE/systemd/"
crontab -l > "$STAGE/etc/crontab.txt" 2>/dev/null || echo "(无 crontab)" > "$STAGE/etc/crontab.txt"

echo "=== 4) 环境摘要（恢复时对照用）==="
{
    echo "# 板端环境摘要 $(date)"
    echo "hostname: $(hostname)"
    echo "kernel  : $(uname -a)"
    echo "os      : $(. /etc/os-release; echo $PRETTY_NAME)"
    echo "glibc   : $(ldd --version | head -1)"
    echo "python  : $(python3 -V 2>&1)"
    echo "ip      : $(ip -4 -br addr | tr '\n' ';')"
    echo "route   : $(ip route | tr '\n' ';')"
    echo "--- 运行中的 glc 相关进程 ---"
    ps -eo pid,args | grep -E "glc_|gige_" | grep -v grep
    echo "--- /opt/MVS 关键库 ---"
    ls -la /opt/MVS/lib/aarch64/libMvCameraControl.so* 2>/dev/null
    echo "--- 磁盘 ---"
    df -h / /tmp | tail -2
} > "$STAGE/ENV.txt" 2>&1

echo "=== 5) 打包 ==="
if ! tar czf "$OUT.tar.gz" -C "$(dirname "$STAGE")" "$(basename "$STAGE")"; then
    echo "!! 打包失败（/tmp 满？）—— 备份不完整，别当成功" >&2
    exit 1
fi
SIZE=$(stat -c%s "$OUT.tar.gz" 2>/dev/null || echo 0)
if [ "${SIZE:-0}" -lt 1024 ]; then
    echo "!! 备份包只有 $SIZE 字节，异常，中止" >&2
    exit 1
fi
echo "产物: $OUT.tar.gz  ($SIZE B)"

echo "=== 6) md5 清单 ==="
( cd "$STAGE" && find . -type f -exec md5sum {} \; | sort -k2 ) > "$OUT.md5.txt"
cp -p "$OUT.md5.txt" /root/board_backup_latest.md5.txt
cp -p "$OUT.tar.gz"  /root/board_backup_latest.tar.gz
wc -l < "$OUT.md5.txt" | xargs -I{} echo "清单 {} 个文件 -> $OUT.md5.txt"
echo
echo "--- 清单前 25 行 ---"
head -25 "$OUT.md5.txt"
echo
echo "完成。把这两个文件拷走即可："
echo "  $OUT.tar.gz"
echo "  $OUT.md5.txt"
