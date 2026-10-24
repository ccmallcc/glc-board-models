#!/bin/bash
# 在 A 板上量 s4（int8 整图）的 total_hard_time，把"NPU 真算"和"其它"分开
# —— B 那边说"s4 每算子 24~31 ms ⇒ 逐算子调度开销是主因"，但那个推断没有 hard_time 支撑
cd /root || exit 1
YH=/root/bf16probe/y_hat.ftmp
[ -f "$YH" ] || { echo "!! 缺 $YH"; exit 1; }
echo "  输入 y_hat: $(stat -c%s $YH) B  md5=$(md5sum $YH | cut -d' ' -f1)"

run_one () {
  local tag="$1" json="$2" raw="$3" vid="$4"
  echo "############ $tag ############"
  echo "  模型: $(stat -c%s $json) B json / $(stat -c%s $raw) B raw"
  local d=/tmp/s4t_$tag
  rm -rf $d; mkdir -p $d
  local S=$(date +%s)
  /usr/bin/icraft-run --json "$json" --raw "$raw" --input $YH \
      --backends 'ZG330,axi://zg330aiu;Host' --log_path $d \
      --log_time --dump_format SFB --dump_ftmp "$vid" > $d/out.log 2>&1
  local RC=$? E=$(date +%s)
  echo "  rc=$RC  **整段墙钟 $((E-S)) s**"
  tr -d '\033' < $d/out.log | grep -aiE "total_hard_time|total_time|hard" | head -6 | sed 's/^/    /'
  ls -l $d/*/ftmpSFB/*.ftmp 2>/dev/null | head -2 | awk '{printf "    产物 %s B\n",$5}'
  echo
}

echo "############################################################################"
echo "# A 板 s4（生成器）计时：整图 int8  vs  整图 bf16+--compress"
echo "# 目的：看「NPU 真算」占多少 —— 这直接决定 B 那边 42 s 的解码该怎么优化"
echo "############################################################################"
echo

run_one "int8" /root/glc/models/s4_int8/s4_gs_generator_ZG.json \
               /root/glc/models/s4_int8/s4_gs_generator_ZG.raw 4107

if [ -f /root/glc/models/s4_bf16/s4_gs_generator_ZG.json ]; then
  echo "（bf16 整图需要 --compress，否则会 sync failed）"
  d=/tmp/s4t_bf16; rm -rf $d; mkdir -p $d
  S=$(date +%s)
  /usr/bin/icraft-run --json /root/glc/models/s4_bf16/s4_gs_generator_ZG.json \
      --raw /root/glc/models/s4_bf16/s4_gs_generator_ZG.raw --input $YH \
      --backends 'ZG330,axi://zg330aiu;Host' --log_path $d \
      --log_time --compress --dump_format SFB --dump_ftmp 4107 > $d/out.log 2>&1
  RC=$?; E=$(date +%s)
  echo "############ bf16 + --compress ############"
  echo "  rc=$RC  **整段墙钟 $((E-S)) s**"
  tr -d '\033' < $d/out.log | grep -aiE "total_hard_time|total_time" | head -3 | sed 's/^/    /'
  echo
fi

echo "=== 参照：s1（编码器，828 算子，int8）==="
echo "  已知实测 total_hard_time = 346 ms（常驻引擎下 forward 平均 0.3505 s）"
echo "  即 **0.42 ms/算子**"
echo
echo "=== 对照 B 的 5 段数据（他们文档里的实测）==="
printf "  %-6s %-6s %-10s %s\n" "段" "算子数" "耗时(s)" "每算子(ms)"
printf "  %-6s %-6d %-10s %.1f\n" s4a   86  "0.8"     "$(awk 'BEGIN{print 0.8/86*1000}')"
printf "  %-6s %-6d %-10s %.1f\n" s4b1  643 "15.7~20.2" "$(awk 'BEGIN{print 15.7/643*1000}')"
printf "  %-6s %-6d %-10s %.1f\n" s4b2  148 "4.0"     "$(awk 'BEGIN{print 4.0/148*1000}')"
printf "  %-6s %-6d %-10s %.1f\n" s4b3  147 "4.5~10.1" "$(awk 'BEGIN{print 4.5/147*1000}')"
printf "  %-6s %-6d %-10s %.1f\n" s4b4  31  "2.2"     "$(awk 'BEGIN{print 2.2/31*1000}')"
echo S4TIME_DONE
