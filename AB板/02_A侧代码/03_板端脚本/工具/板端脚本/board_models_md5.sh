#!/bin/sh
echo "=== 板端 /root/glc/models 的 _ZG 产物 ==="
for n in s1_encoder_ga_hyper s2_hyperdec_fusion s3_phase1 s3_phase2 s3_phase3; do
  for e in json raw; do
    f=/root/glc/models/${n}_ZG.${e}
    if [ -f "$f" ]; then
      printf "%s  %s  %s\n" "$(md5sum $f | cut -d' ' -f1)" "$(stat -c%s $f)" "$f"
    else
      printf "%-34s %s\n" "(缺)" "$f"
    fi
  done
done
