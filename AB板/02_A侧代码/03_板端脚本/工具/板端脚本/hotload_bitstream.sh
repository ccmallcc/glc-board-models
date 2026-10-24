#!/bin/bash
# 板上执行：把 /lib/firmware/ 下的 .bin 热加载进 PL（不重启）。
#
# 用法: hotload_bitstream.sh <name>.bin
#   <name>.bin 必须已经在 /lib/firmware/ 下。
#
# 原理：Linux FPGA manager 框架（CONFIG_FPGA_MGR_FMQL_FPGA=y）通过
#       /sys/class/fpga_manager/fpga0/firmware 接收位流名并重新配置 PL。
#       .bin 必须是「.bit 去头 + 32 位字字节反序」，用 工具/bit_to_bin.py 生成。
#
# 【实测 2026-09-22】写两次均返回 0，state 全程 operating，
#   且加载后 S1 推理 total_hard_time = 346.745 ms（对照 346.753 ms，差 0.008 ms）。
set -u

FM=/sys/class/fpga_manager/fpga0
FW=${1:-}

if [ -z "$FW" ]; then
  echo "用法: $0 <name>.bin   （须已放在 /lib/firmware/ 下）"
  echo "现有可选："
  ls -1 /lib/firmware/*.bin 2>/dev/null | xargs -n1 basename 2>/dev/null | sed 's/^/  /'
  exit 2
fi

if [ ! -f "/lib/firmware/$FW" ]; then
  echo "错误：/lib/firmware/$FW 不存在"
  exit 3
fi

if [ ! -w "$FM/firmware" ]; then
  echo "错误：$FM/firmware 不可写（需要 root）"
  exit 4
fi

echo "=========== 热加载 $FW ==========="
echo "加载前 state = $(cat $FM/state)"
MARK=$(dmesg | wc -l)

if ! echo "$FW" > "$FM/firmware"; then
  echo "错误：写 $FM/firmware 失败"
  exit 5
fi
sleep 1

NEWSTATE=$(cat $FM/state)
echo "加载后 state = $NEWSTATE"
echo "--- dmesg 新增行 ---"
dmesg | tail -n +$((MARK + 1))

if [ "$NEWSTATE" != "operating" ]; then
  echo "⚠ state 不是 operating（=$NEWSTATE）—— PL 可能没配上，重启可恢复"
  exit 6
fi

echo "--- dmesg 里有没有报错 ---"
if dmesg | tail -n +$((MARK + 1)) | grep -qiE 'fail|error|timeout'; then
  echo "⚠ 上面出现了 fail/error 字样，请人工确认"
  exit 7
fi

echo "✅ 热加载完成（未重启）"
echo "   提示：PL 已被整体重配，正在跑的板端程序需要重新启动。"
