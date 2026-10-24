#==========================================================================
# preflight.tcl —— 大构建之前的快速前置综合
#
# 目的（都必须在花 1 小时跑官方工程之前拿到答案）：
#   1. rans_top 到底能不能被 Vivado 综合掉（尤其 $readmemh 建 ROM）
#   2. 真实资源占用（BRAM 是最大风险：我们约 3 Mb，器件共 9.54 Mb，NPU 还要用）
#   3. $readmemh 的**绝对路径**在综合时能否解析
#
# ⚠️ 首跑踩坑（已修）：忘了传 -generic MEM_ROOT，RTL 用默认值 "mem"，
#    综合器报 `could not open $readmem data file 'mem/cdf_flat.hex'`，
#    五个 ROM 全空，并连带刷出 100 条 `Net cdf_* does not have driver`。
#    那些 "no driver" 不是独立问题，是 $readmemh 失败的后果。
#==========================================================================
set rb E:/pl_work/rans_board

read_verilog [list \
    $rb/rtl/rans_top.v \
    $rb/rtl/rans_cdf.v \
    $rb/rtl/rans_enc_stream.v \
    $rb/rtl/rans_enc_put.v \
    $rb/rtl/reg_ctrl.v \
    $rb/rtl/pulse_cross.v ]

# ⚠️ 必须显式传 MEM_ROOT，否则 $readmemh 找不到表
synth_design -top rans_top -part xc7z030ffg676-2 -flatten_hierarchy none \
    -generic MEM_ROOT=$rb/mem

puts "=================================================================="
puts "== PREFLIGHT SYNTH OK"
puts "=================================================================="
report_utilization -file $rb/preflight_util.rpt
report_utilization

set bram [get_cells -hier -filter {PRIMITIVE_GROUP == BRAM}]
puts "== BRAM cells: [llength $bram]"
foreach c $bram { puts "==   $c : [get_property REF_NAME $c]" }

puts "=================================================================="
puts "== DONE"
puts "=================================================================="
