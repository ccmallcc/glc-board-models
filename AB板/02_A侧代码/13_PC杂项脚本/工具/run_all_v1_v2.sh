#!/bin/bash
# Full offline entropy-coding regression: V1 (rANS core) + V2 (tables + board path)
R=/mnt/e/fudanwei/工作区/rans
rc=0

echo "########## V1: rANS 内核 vs compressai（5 组向量）##########"
bash "$R/run_all.sh" > /tmp/v1.txt 2>&1 || rc=1
grep -E "PASS|FAIL|overall" /tmp/v1.txt
echo "V1_EXIT=$?"

echo
echo "########## V2-a: 二进制表一致性 + scale->index（400,048 条）##########"
bash "$R/run_v2_check.sh" > /tmp/v2a.txt 2>&1 || rc=1
grep -E "完全一致|完全一致|全部通过|向量条数|循环版|二分版|结论|不一致" /tmp/v2a.txt

echo
echo "########## V2-b: 板端路径端到端（4 真实相位 + STRESS）##########"
bash "$R/run_v2_board.sh" > /tmp/v2b.txt 2>&1 || rc=1
grep -E "^--- |板端输出|逐字节   |overall|符号数" /tmp/v2b.txt

echo
echo "=================================================="
[ $rc -eq 0 ] && echo "总判定: ALL-PASS ✅" || echo "总判定: SOME-FAILED ❌"
exit $rc
