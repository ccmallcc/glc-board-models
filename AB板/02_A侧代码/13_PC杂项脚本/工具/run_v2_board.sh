#!/bin/bash
# V2 integration: board-side encoder (compact table + scale->index) vs compressai
cd /mnt/e/fudanwei/工作区 || exit 2
echo "===== 导出板端路径向量（4 个相位）====="
for ph in 0 1 2 3; do
  python3 tools/export_rans_board.py --ops entropy_ops/img0 --phase $ph \
      --out rans/boardvec_phase$ph.txt 2>&1 | grep -v FutureWarning | grep -v 'warnings.warn'
done
echo
echo "===== 导出板端 STRESS 向量（覆盖全部 64 行 CDF + escape/bypass）====="
python3 tools/export_rans_board_stress.py --out rans/boardvec_stress.txt 2>&1 \
    | grep -v FutureWarning | grep -v 'warnings.warn'
echo
echo "===== 编译并运行板端编码器 ====="
cd rans || exit 2
g++ -O2 -std=c++11 -o rans_board rans_board.cpp || exit 3
fail=0
for name in phase0 phase1 phase2 phase3 stress; do
  echo "--- $name"
  if ./rans_board boardvec_$name.txt glc_cdf_table.bin; then :; else fail=1; fi
  echo
done
echo "---- overall: $([ $fail -eq 0 ] && echo ALL-PASS || echo SOME-FAILED)"
exit $fail
