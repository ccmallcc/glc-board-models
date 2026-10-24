#!/bin/bash
# 重取 S1 计时拆解，剥掉终端控制码
set -u
BOARD=192.168.31.72
PASS=fmsh
SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=8"
$SSH root@$BOARD "bash -s" <<'REMOTE' 2>&1 | sed 's/\x1b\[[0-9;]*[A-Za-z]//g' | grep -v '^\[2K' | grep -v '^\s*$'
M=/root/glc/models; cd /root/glc/run/s1 || exit 1

echo "########## A. 逐算子求和（默认参数）##########"
awk '/^opId:/ {
  for(i=1;i<=NF;i++){ if($i=="wall:") w+=$(i+1); if($i=="hard:") h+=$(i+1); if($i=="other:") o+=$(i+1); if($i=="mem:") m+=$(i+1) }
  n++
} END { printf "    算子行=%d  sum_wall=%.1f  sum_hard=%.1f  sum_mem=%.1f  sum_other=%.1f  (ms)\n", n, w, h, m, o }' /tmp/s1.txt

echo
echo "########## B. Summary 里的那行 total_* ##########"
grep -E 'total_time|total_hard_time' /tmp/s1.txt | head -2 | sed 's/^/    /'

echo
echo "########## C. ocmopt 各档（墙钟 / hard）##########"
for opt in -1 0 1 2 3; do
  rm -rf lg; mkdir -p lg
  S=$(date +%s%N)
  /usr/bin/icraft-run --json $M/s1_encoder_ga_hyper_ZG.json --raw $M/s1_encoder_ga_hyper_ZG.raw \
    --input in0.ftmp --backends "ZG330,axi://zg330aiu;Host" --log_path lg --log_time \
    --ocmopt $opt > /tmp/s1o.txt 2>&1
  RC=$?; E=$(date +%s%N)
  H=$(grep -oE 'total_hard_time: *[0-9.]+' /tmp/s1o.txt | head -1 | grep -oE '[0-9.]+')
  printf "    ocmopt=%-2s rc=%s  墙钟=%6s ms   hard=%s ms\n" "$opt" "$RC" "$(( (E-S)/1000000 ))" "$H"
done

echo
echo "########## D. 有没有 OCM/方案 相关打印 ##########"
grep -iE 'ocm|plan|方案|optimi' /tmp/s1o.txt | head -8 | sed 's/^/    /' || echo "    (无)"

echo
echo "########## E. 只加载不推理？（拿掉 --input 会怎样）##########"
rm -rf lg; mkdir -p lg
S=$(date +%s%N)
/usr/bin/icraft-run --json $M/s1_encoder_ga_hyper_ZG.json --raw $M/s1_encoder_ga_hyper_ZG.raw \
  --input in0.ftmp --backends 'ZG330,axi://zg330aiu;Host' --log_path lg > /tmp/s1n.txt 2>&1
E=$(date +%s%N); echo "    不加 --log_time 的墙钟=$(( (E-S)/1000000 ))ms  rc=$?"
REMOTE
