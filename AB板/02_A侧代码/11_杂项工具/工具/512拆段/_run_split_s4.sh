#!/bin/bash
# 512 s4 拆两段在板上跑：segA -> 边界张量 -> segB，并各自报 hard time。
#
# 为什么要这个脚本：两段是**两次独立的 icraft-run 进程**，中间要有人把 a 的输出
# 落到盘上再喂给 b；而且 dump 出来的文件名是 icraft 的 v_id（每次可能不同），
# 不能写死，只能"跑完去 logs 里找唯一那个 16,777,216 字节的张量"。
#
# 用法: bash run_split_s4.sh [--lazy]
set -u
A_DIR=/root/exp512/models512split/a
B_DIR=/root/exp512/models512split/b
W=/root/exp512/chain512
LAZY=""
[ "${1:-}" = "--lazy" ] && LAZY="--lazy_load"

rm -rf "$W"
mkdir -p "$W"
cp /root/exp512/val512/in0.ftmp "$W/in0.ftmp"
cd "$W" || exit 1

echo "================ segA ================"
/usr/bin/icraft-run --json "$A_DIR/s4_512_a_ZG.json" --raw "$A_DIR/s4_512_a_ZG.raw" \
    --input in0.ftmp --backends "ZG330,axi://zg330aiu;Host" \
    --log_path logs_a --log_time --ocmopt 1 $LAZY --dump_output 2>&1 \
  | grep -E "total_hard_time|Required bytes|sync failed|Exception info"

MID=$(find logs_a -name '*.ftmp' -size +10M | head -1)
if [ -z "${MID:-}" ]; then echo "!! segA 没产出边界张量"; exit 2; fi
echo "  边界张量: $MID  $(stat -c%s "$MID") B"
cp "$MID" in0_b.ftmp

echo "================ segB ================"
/usr/bin/icraft-run --json "$B_DIR/s4_512_b_ZG.json" --raw "$B_DIR/s4_512_b_ZG.raw" \
    --input in0_b.ftmp --backends "ZG330,axi://zg330aiu;Host" \
    --log_path logs_b --log_time --ocmopt 1 $LAZY --dump_output 2>&1 \
  | grep -E "total_hard_time|Required bytes|sync failed|Exception info"

OUT=$(find logs_b -name '*.ftmp' -size +2M | head -1)
if [ -z "${OUT:-}" ]; then echo "!! segB 没产出图像"; exit 3; fi
echo "  输出图像: $OUT  $(stat -c%s "$OUT") B"
echo "DONE out=$OUT"
