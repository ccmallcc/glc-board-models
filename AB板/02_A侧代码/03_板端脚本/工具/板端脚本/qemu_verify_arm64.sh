#!/bin/bash
# Run the *cross-compiled aarch64* board encoder under qemu-user-static and
# compare against the x86_64 build, on all V2 regression vectors.
set -e
SRC=/mnt/e/fudanwei/工作区/rans
OUT=$SRC/board_bin
QEMU=qemu-aarch64-static
cd "$SRC"

echo "############ A. aarch64 (cross-compiled, static) under qemu ############"
fail=0
for name in phase0 phase1 phase2 phase3 stress; do
  printf '%-8s ' "$name"
  if $QEMU "$OUT/rans_board_arm64_static" "boardvec_$name.txt" glc_cdf_table.bin >/tmp/arm_$name.log 2>&1; then
    echo "PASS   $(grep -o '板端输出 : [0-9]* bytes' /tmp/arm_$name.log | head -1)   $(tail -2 /tmp/arm_$name.log | head -1 | tr -d '\r')"
  else
    echo "FAIL"; fail=1
  fi
done
echo "---- aarch64 overall: $([ $fail -eq 0 ] && echo ALL-PASS || echo SOME-FAILED)"
echo

echo "############ B. x86_64 (native, same source) ############"
fail2=0
for name in phase0 phase1 phase2 phase3 stress; do
  printf '%-8s ' "$name"
  if ./rans_board "boardvec_$name.txt" glc_cdf_table.bin >/tmp/x86_$name.log 2>&1; then
    echo "PASS   $(grep -o '板端输出 : [0-9]* bytes' /tmp/x86_$name.log | head -1)"
  else
    echo "FAIL"; fail2=1
  fi
done
echo "---- x86_64 overall: $([ $fail2 -eq 0 ] && echo ALL-PASS || echo SOME-FAILED)"
echo

echo "############ C. aarch64 vs x86_64 输出逐字比对 ############"
same=0; diff=0
for name in phase0 phase1 phase2 phase3 stress; do
  # compare everything except the banner lines
  if diff <(grep -v '^vector' /tmp/arm_$name.log) <(grep -v '^vector' /tmp/x86_$name.log) >/dev/null 2>&1; then
    echo "  $name  日志一致 ✅"; same=$((same+1))
  else
    echo "  $name  日志有差异 ❌"; diff=$((diff+1))
  fi
done
echo "---- 一致 $same / $((same+diff))"

echo
echo "############ D. V1 rANS core (rans_port) under qemu ############"
head -20 "$SRC/run_all.sh"
