#!/bin/bash
#======================================================================
# c2sim.sh —— 跑 C2（PL 熵编码器）的仿真
# 纯 ASCII 路径入口，中文路径写在文件里面（Qoder 在 Windows 侧调它）。
# 用法： wsl -d Ubuntu-22.04 -- bash /mnt/e/fudanwei/_logs/sim/c2sim.sh
# 退出码：0=全过、2=有 FAIL、3=有编译失败
#======================================================================
exec bash "/mnt/e/fudanwei/GLC-共享包/工具/run_sim.sh" "/mnt/e/fudanwei/GLC-共享包/C2_PL熵编码器"