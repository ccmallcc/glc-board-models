#!/bin/bash
# try icraft-run memory-related switches on the bf16 s4 model (ASCII only)
P=/root/bf16flags
rm -rf $P; mkdir -p $P; cd $P
cp /root/bf16probe/y_hat.ftmp $P/ 2>/dev/null || { echo "no input"; exit 1; }
B=/root/glc/models/s4_bf16/s4_gs_generator_ZG
IC=/usr/bin/icraft-run

try () {
  local tag="$1"; shift
  local d=$P/$tag
  mkdir -p $d
  echo "=============================================================="
  echo "### $tag    extra: $*"
  echo "=============================================================="
  timeout 420 $IC --json $B.json --raw $B.raw --input $P/y_hat.ftmp \
      --backends 'ZG330,axi://zg330aiu;Host' --log_path $d/log \
      --dump_format SFB --dump_ftmp 4107 "$@" > $d/out.log 2>&1
  local rc=$?
  echo "  rc=$rc   elapsed=${SECONDS}s"
  grep -a -o "Network size:[0-9]*[^!]*!" $d/out.log | head -1
  grep -a -o "Exception info : [^\[]*" $d/out.log | head -1
  ls -l $d/log/*/ftmpSFB/*.ftmp 2>/dev/null | awk '{print "  DUMP "$5" B  "$9}'
  echo
}

try base
try compress --compress
try mergehardop --merge_hardop
try ocm0 --ocmopt 0
try ocm2 --ocmopt 2
try compress_merge --compress --merge_hardop

echo BF16FLAGS_DONE
