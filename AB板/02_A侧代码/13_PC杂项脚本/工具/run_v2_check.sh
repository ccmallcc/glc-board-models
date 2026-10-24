#!/bin/bash
# V2 verification: build and run the index/blob checker
cd /mnt/e/fudanwei/工作区/rans || exit 2
g++ -O2 -std=c++11 -o rans_index_check rans_index_check.cpp || exit 3
./rans_index_check vector_indexes.txt glc_cdf_table.bin
rc=$?
echo "---- exit=$rc"
exit $rc
