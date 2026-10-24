#!/bin/bash
# GLC 2026-10-08: 把 S1 的 6.6 秒拆开 —— 是 SD 卡 I/O 还是 CPU 反序列化？
M=/root/glc/models
echo "=== 模型文件大小 ==="
ls -l $M/*_ZG.raw
echo
echo "=== /dev/shm 可用空间（RAM 盘）==="
df -h /dev/shm
echo
echo "=== SD 卡读吞吐 第1次（冷）==="
sync
dd if=$M/s1_encoder_ga_hyper_ZG.raw of=/dev/null bs=1M 2>&1 | tail -1
echo "=== SD 卡读吞吐 第2次（page cache 命中）==="
dd if=$M/s1_encoder_ga_hyper_ZG.raw of=/dev/null bs=1M 2>&1 | tail -1
echo
cd /root/glc/run/s1 || exit 1
ls -l in0.ftmp
RUN="/usr/bin/icraft-run --json $M/s1_encoder_ga_hyper_ZG.json --raw $M/s1_encoder_ga_hyper_ZG.raw --input in0.ftmp --backends ZG330,axi://zg330aiu;Host --log_path logs --log_time --ocmopt 1 --dump_format SFB --dump_ftmp 3310,3314"
echo
echo "=== S1 icraft-run 第 1 次 ==="
START=$(date +%s.%N)
/usr/bin/icraft-run --json $M/s1_encoder_ga_hyper_ZG.json --raw $M/s1_encoder_ga_hyper_ZG.raw \
  --input in0.ftmp --backends "ZG330,axi://zg330aiu;Host" --log_path logs --log_time --ocmopt 1 \
  --dump_format SFB --dump_ftmp 3310,3314 > /tmp/s1a.log 2>&1
RC1=$?
END=$(date +%s.%N)
echo "  rc=$RC1  wall=$(echo "$END - $START" | bc) s"
grep -E 'total_hard_time|total_time' /tmp/s1a.log | tail -3
echo
echo "=== S1 icraft-run 第 2 次（同一条命令，page cache 必然命中）==="
START=$(date +%s.%N)
/usr/bin/icraft-run --json $M/s1_encoder_ga_hyper_ZG.json --raw $M/s1_encoder_ga_hyper_ZG.raw \
  --input in0.ftmp --backends "ZG330,axi://zg330aiu;Host" --log_path logs --log_time --ocmopt 1 \
  --dump_format SFB --dump_ftmp 3310,3314 > /tmp/s1b.log 2>&1
RC2=$?
END=$(date +%s.%N)
echo "  rc=$RC2  wall=$(echo "$END - $START" | bc) s"
grep -E 'total_hard_time|total_time' /tmp/s1b.log | tail -3
echo
echo "=== S1 icraft-run 第 3 次 + --lazy_load ==="
START=$(date +%s.%N)
/usr/bin/icraft-run --json $M/s1_encoder_ga_hyper_ZG.json --raw $M/s1_encoder_ga_hyper_ZG.raw \
  --input in0.ftmp --backends "ZG330,axi://zg330aiu;Host" --log_path logs --log_time --ocmopt 1 \
  --lazy_load --dump_format SFB --dump_ftmp 3310,3314 > /tmp/s1c.log 2>&1
RC3=$?
END=$(date +%s.%N)
echo "  rc=$RC3  wall=$(echo "$END - $START" | bc) s  (--lazy_load)"
grep -E 'total_hard_time|total_time' /tmp/s1c.log | tail -3
echo
echo "=== 两次 S1 输出的 ftmp 是否一致（顺便验可复现性）==="
ls -l logs/s1/ftmpSFB/ 2>/dev/null | head
md5sum logs/s1/ftmpSFB/*.ftmp 2>/dev/null
echo "MEASURE_DONE"
