#!/bin/bash
# 查板子上有没有加载 PL 位流 / NPU 是否需要位流
PASS=fmsh
SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
$SSH root@192.168.0.2 'bash -s' <<'REMOTE'
echo "########## A. /root/bits ##########"
ls -la /root/bits 2>/dev/null || echo "  (/root/bits 不存在)"
echo
echo "########## B. 全盘找位流 ##########"
find / -xdev \( -name 'BOOT*.bin' -o -name '*.bit' -o -name 'BOOT*.zip' \) 2>/dev/null | head -20 || true
echo
echo "########## C. FPGA 配置状态 ##########"
ls /sys/class/fpga* /sys/class/fpga_manager 2>/dev/null || echo "  (无 fpga sysfs 节点)"
cat /sys/class/fpga_manager/*/state 2>/dev/null || true
ls /dev/xdevcfg /dev/devcfg* 2>/dev/null || echo "  (无 devcfg 节点)"
echo
echo "########## D. 启动日志里有没有 FPGA/PL 加载 ##########"
dmesg 2>/dev/null | grep -i -E 'fpga|devcfg|xdevcfg|bitstream|zynq|pcw' | head -20 || echo "  (无)"
echo
echo "########## E. NPU 相关的内核/寄存器线索 ##########"
cat /proc/device-tree/model 2>/dev/null; echo
ls /proc/device-tree/ 2>/dev/null | head -30
echo
echo "########## F. icraft 的环境变量/配置要求 ##########"
strings /usr/bin/icraft-run 2>/dev/null | grep -i -E 'ICRAFT|LD_LIBRARY|devcfg|/dev/mem|/root/bits' | head -15
echo
echo "########## G. 官方 README 里怎么说 ##########"
find / -xdev -maxdepth 3 -iname 'README*' 2>/dev/null | head
REMOTE
