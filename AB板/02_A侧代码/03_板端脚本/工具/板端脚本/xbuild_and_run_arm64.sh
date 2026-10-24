#!/bin/bash
# Cross-compile board binaries, ship them to a Windows-visible dir, and (if
# qemu-user is available) actually EXECUTE them here to prove they work.
set -e
SRC=/mnt/e/fudanwei/工作区/rans
OUT=/mnt/e/fudanwei/工作区/rans/board_bin
mkdir -p "$OUT"
cd "$OUT"

echo "=== build (dynamic + static) ==="
for f in rans_port glc2_pack rans_board; do
  aarch64-linux-gnu-g++ -O2 -std=c++11 -I"$SRC" -o "${f}_arm64"       "$SRC/$f.cpp"
  aarch64-linux-gnu-g++ -O2 -std=c++11 -I"$SRC" -static -o "${f}_arm64_static" "$SRC/$f.cpp"
  echo "  $f ok"
done
echo

echo "=== file ==="
file rans_port_arm64 glc2_pack_arm64 rans_board_arm64
echo
file rans_port_arm64_static | sed 's/,.*//'
echo

echo "=== sizes ==="
ls -l --block-size=K rans_port_arm64* glc2_pack_arm64* rans_board_arm64* | awk '{print $5, $9}'
echo

echo "=== qemu-user-static present? ==="
if command -v qemu-aarch64-static >/dev/null 2>&1; then
  echo "YES: $(command -v qemu-aarch64-static)"
  QEMU=qemu-aarch64-static
elif command -v qemu-aarch64 >/dev/null 2>&1; then
  echo "YES: $(command -v qemu-aarch64)"
  QEMU=qemu-aarch64
else
  echo "NO qemu installed."
  echo "--- try apt (timeboxed) ---"
  timeout 180 apt-get install -y -q qemu-user-static >/tmp/aptq.log 2>&1 && echo "apt install OK" || echo "apt install FAILED (see /tmp/aptq.log tail)"
  tail -3 /tmp/aptq.log 2>/dev/null || true
  command -v qemu-aarch64-static >/dev/null 2>&1 && QEMU=qemu-aarch64-static || QEMU=
fi
echo

if [ -n "$QEMU" ]; then
  echo "=== 🚀 RUN the aarch64 binary under qemu: rans_port ==="
  cd "$SRC"
  $QEMU "$OUT/rans_port" 2>&1 | head -20 || true
  echo
  echo "=== 🚀 RUN the V2 board regression (phase0..3 + stress) under qemu ==="
  fail=0
  for name in phase0 phase1 phase2 phase3 stress; do
    printf '%-8s ' "$name"
    if $QEMU "$OUT/rans_board" "boardvec_$name.txt" glc_cdf_table.bin >/tmp/q_$name.log 2>&1; then
      echo "PASS  ($(tail -1 /tmp/q_$name.log | tr -d '\r'))"
    else
      echo "FAIL  (see /tmp/q_$name.log)"; fail=1
    fi
  done
  echo "---- qemu overall: $([ $fail -eq 0 ] && echo ALL-PASS || echo SOME-FAILED)"
else
  echo "(skipping execution: no qemu)"
fi
