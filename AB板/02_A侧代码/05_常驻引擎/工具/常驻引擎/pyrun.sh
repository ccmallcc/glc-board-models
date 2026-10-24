#!/bin/bash
# GLC 2026-10-08: 通用远端 python 执行器 —— 解决"PowerShell 吃引号"的老问题
#   用法: bash /root/pyrun.sh <脚本> [参数...]
#   作用: 跑脚本、去掉进度条转义、打印 rc
S="$1"; shift
if [ -z "$S" ] || [ ! -f "$S" ]; then echo "用法: pyrun.sh <脚本> [参数...]"; exit 2; fi
python3 -u "$S" "$@" > /tmp/pyrun.log 2>&1
RC=$?
echo "rc=$RC"
# 去掉 ESC 序列与 progress 用的 [2K
tr -d '\033' < /tmp/pyrun.log | sed 's/\[2K//g'
echo "PYRUN_DONE rc=$RC"
