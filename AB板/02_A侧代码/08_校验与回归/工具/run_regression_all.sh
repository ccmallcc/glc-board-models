#!/bin/bash
# Full offline regression after the dataset audit + all corrections.
R=/mnt/e/fudanwei/工作区/rans
rc=0
echo "########## V1 + V2（熵编码内核 / 常量表 / 板端路径）##########"
bash "$R/run_all_v1_v2.sh" > /tmp/reg12.log 2>&1 || rc=1
grep -E "PASS|overall|完全一致|全部通过|向量条数|循环版|二分版|结论|总判定" /tmp/reg12.log

echo
echo "########## V5（自产容器闭环，默认输入= 真 Kodak）##########"
bash "$R/run_v5_dump.sh" 4 256 /mnt/e/fudanwei/工作区/v5_real /mnt/e/fudanwei/工作区/testset/kodak > /tmp/reg5a.log 2>&1 || rc=1
grep -E "input dir|phase [0-9]|img[0-9]" /tmp/reg5a.log | head -8
bash "$R/run_v5_pack2.sh" /mnt/e/fudanwei/工作区/v5_real 4 > /tmp/reg5b.log 2>&1 || rc=1
grep -E "逐字节 vs 参考|第二分辨率" /tmp/reg5b.log

echo
echo "=================================================="
[ $rc -eq 0 ] && echo "总判定: ALL-PASS ✅" || echo "总判定: SOME-FAILED ❌"
exit $rc
