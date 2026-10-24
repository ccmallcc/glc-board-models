#==========================================================================
# build_rans.tcl —— 在官方 fpai_demo 工程里，把加法器算子换成我们的 rANS
#                   熵编码器，出带 NPU(AI_Mate) + rANS 的完整位流。
#
# 用法：E:\pl_work\rans_board\run_build.bat
#
# 与 build_led.tcl 的差别：**不改建新工程，直接打开官方工程**
#   —— 因为器件库替换/BD/MIG/GTX IP 都在工程里，重建代价太高。
#
# 唯一的功能改动在 rtl/ai7030_edif_top.v：
#   adder_top U_adder_top(...)  ->  rans_top U_rans_top(...)
#   总线契约、位宽（512b 数据 / 32b 寄存器）一字不改。
#
# ⚠️ reg_ctrl.v / pulse_cross.v **不加**：官方工程 rtl/adder_op/ 下已有
#    同名模块，重复添加会造成模块重复定义。已核对两者 SHA256 相同
#    （repo rtl/official/  ==  工程 rtl/adder_op/）。
#==========================================================================

set root E:/pl_work/fpai_demo/fpai_demo_fpga
set rb   E:/pl_work/rans_board
set jfm  E:/JFM_Kits

set ::env(JFM_PATH)          $jfm
set ::env(FMSH_PROCISE_PATH) E:/fudanwei/Procise

puts "=================================================================="
puts "== JFM_PATH          = $::env(JFM_PATH)"
puts "== FMSH_PROCISE_PATH = $::env(FMSH_PROCISE_PATH)"
puts "=================================================================="

# ---- 打开官方工程 ----
puts "== open_project $root/fpai_demo_vivado.xpr"
open_project $root/fpai_demo_vivado.xpr

if {[catch {set_property ip_cache_scope none [current_project]} e]} {
    puts "== ip_cache_scope 设置失败（可忽略）：$e"
}

# ---- 加入我们的计算核（4 个文件；RTL 依赖 reg_ctrl/pulse_cross 用工程自带）----
puts "== add_files rANS rtl"
add_files -norecurse [list \
    $rb/rtl/rans_top.v \
    $rb/rtl/rans_cdf.v \
    $rb/rtl/rans_enc_stream.v \
    $rb/rtl/rans_enc_put.v ]

set_property top ai7030_edif_top [current_fileset]
update_compile_order -fileset sources_1

puts "== part = [get_property PART [current_project]]"
puts "== top  = [get_property top [current_fileset]]"
puts "== dir  = [get_property DIRECTORY [current_project]]"

# ---- 复旦微 IP_PATCH ----
puts "== source run.tcl ..."
source $::env(JFM_PATH)/ip_patch/run.tcl
puts "== add_hook_tcl_to_prj ..."
add_hook_tcl_to_prj
puts "== replace_7z030ai_file ..."
replace_7z030ai_file
if {[catch {database_check} e]} { puts "== database_check: $e" }

# ---- 强制重跑（工程里带的是厂家机器上的旧 run 状态）----
foreach r {synth_1 impl_1} { catch { reset_run $r } }

# ---- 综合 ----
puts "=================================================================="
puts "== launch synth_1"
puts "=================================================================="
launch_runs synth_1 -jobs 8
wait_on_run synth_1
puts "== synth STATUS  = [get_property STATUS   [get_runs synth_1]]"
puts "== synth PROGRESS= [get_property PROGRESS [get_runs synth_1]]"
if {[get_property PROGRESS [get_runs synth_1]] != "100%"} {
    error "SYNTH FAILED: [get_property STATUS [get_runs synth_1]]"
}

# ---- 实现 + 位流 ----
# ⚠️ 官方明确：位流不要指定输出路径，补丁会调用 PROCISE 自动打位流补丁
puts "=================================================================="
puts "== launch impl_1 -> write_bitstream"
puts "=================================================================="
launch_runs impl_1 -to_step write_bitstream -jobs 8
wait_on_run impl_1
puts "== impl STATUS   = [get_property STATUS   [get_runs impl_1]]"
puts "== impl PROGRESS = [get_property PROGRESS [get_runs impl_1]]"
if {[get_property PROGRESS [get_runs impl_1]] != "100%"} {
    error "IMPL FAILED: [get_property STATUS [get_runs impl_1]]"
}

open_run impl_1
puts "=================================================================="
puts "== 资源占用"
puts "=================================================================="
report_utilization -file $rb/util_rans.rpt
report_timing_summary -file $rb/timing_rans.rpt -delay_type min_max -max_paths 5

puts "=================================================================="
puts "== 产物"
puts "=================================================================="
foreach b [glob -nocomplain $root/fpai_demo_vivado.runs/impl_1/*.bit] {
    puts "==   $b  ([file size $b] 字节)"
}
puts "=================================================================="
puts "== DONE"
puts "=================================================================="
