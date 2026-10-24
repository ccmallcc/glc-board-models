#!/bin/bash
# V5 step 2: rebuild the shared-encoder harness and re-verify V2 regressions,
# then build the container packer.
cd /mnt/e/fudanwei/工作区/rans || exit 2
set -e
echo "===== rebuild (shared glc_board_encoder.h) ====="
g++ -O2 -std=c++11 -o rans_board rans_board.cpp
g++ -O2 -std=c++11 -o rans_index_check rans_index_check.cpp
g++ -O2 -std=c++11 -o glc2_pack glc2_pack.cpp
echo "BUILD_OK"
echo
echo "===== re-run V2 board regression after refactor ====="
bash run_v2_board.sh 2>&1 | grep -E '^(--- |  *逐字节|====|----)'
