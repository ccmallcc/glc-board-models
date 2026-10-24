#!/bin/bash
# V1 regression: byte-exact rANS cross-check against compressai
cd /mnt/e/fudanwei/工作区/rans || exit 2
fail=0
for v in phase0 phase1 phase2 phase3 stress; do
  printf '%-10s ' "$v"
  if out=$(./rans_port "vector_$v.txt" 2>&1); then
    echo "PASS (exit=0)"
  else
    echo "FAIL (exit=$?)"
    fail=1
  fi
  echo "$out" | sed 's/^/           /'
done
echo "---- overall: $([ $fail -eq 0 ] && echo ALL-PASS || echo SOME-FAILED)"
exit $fail
