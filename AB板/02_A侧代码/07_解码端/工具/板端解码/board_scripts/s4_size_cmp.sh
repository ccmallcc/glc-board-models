#!/bin/bash
# compare "Network size" reported by icraft-run for each s4 build (ASCII only)
P=/root/s4size
rm -rf $P; mkdir -p $P; cd $P
cp /root/bf16probe/y_hat.ftmp $P/ 2>/dev/null || { echo "no y_hat input"; exit 1; }
IC=/usr/bin/icraft-run
for d in s4_int8 s4_bf16; do
  B=/root/glc/models/$d/s4_gs_generator_ZG
  echo "=============================================================="
  echo "### $d   raw=$(stat -c%s $B.raw) B"
  echo "=============================================================="
  timeout 600 $IC --json $B.json --raw $B.raw --input $P/y_hat.ftmp \
      --backends 'ZG330,axi://zg330aiu;Host' --log_path $P/log_$d \
      --dump_format SFB --dump_ftmp 4107 > $P/$d.log 2>&1
  echo "  rc=$?"
  grep -a -o "Network size:[0-9]*[^!]*!" $P/$d.log | head -2
  grep -a -o "device_layer_count: [0-9]*" $P/$d.log | head -2
  grep -a -o "Exception info : [^\[]*" $P/$d.log | head -3
  ls -l $P/log_$d/*/ftmpSFB/*.ftmp 2>/dev/null | head -2
  echo
done
echo "=== board mem / npu dmesg ==="
free -m | head -2
dmesg 2>/dev/null | grep -i -E "npu|zg330|reserved|cmem" | tail -12
echo S4SIZE_DONE
