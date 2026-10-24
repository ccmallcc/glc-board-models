#!/bin/bash
# 查 PL 位流的加载机制（NPU 在 PL 里，没位流就段错误）
PASS=fmsh
SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
$SSH root@192.168.0.2 'bash -s' <<'REMOTE'
echo "########## A. fpga_manager 状态 ##########"
for f in state flags name; do
  printf '  %-6s: %s\n' "$f" "$(cat /sys/class/fpga_manager/fpga0/$f 2>/dev/null)"
done
ls /sys/class/fpga_manager/fpga0/
echo
echo "########## B. /root/boot 里有什么 ##########"
ls -la /root/boot/ 2>/dev/null
echo
echo "########## C. 谁在用 /root/bits ##########"
grep -rl 'bits' /etc/init.d /etc/rc.local /etc/profile.d /usr/local/bin /usr/bin/*.sh /root 2>/dev/null | head -10
echo "--- rc.local ---"; cat /etc/rc.local 2>/dev/null
echo "--- 搜 'bits' 字面 ---"
grep -rn '/root/bits\|bits' /root/login.py /root/tcp_speed_test.py 2>/dev/null | head
echo
echo "########## D. 启动脚本 / systemd 自定义服务 ##########"
ls /etc/systemd/system/*.service 2>/dev/null
systemctl list-units --type=service --state=running 2>/dev/null | head -20
echo
echo "########## E. 全局搜含 'bits' 或 'loadfpga' 的脚本 ##########"
grep -rln 'loadfpga\|fpga_manager\|/root/bits\|xdevcfg' /usr /etc /root /home 2>/dev/null | head -10
echo
echo "########## F. 有没有 bitstream 转换/加载工具 ##########"
for c in fpgautil xdevcfg load_bitstream fpgaconf; do
  printf '  %-16s %s\n' "$c" "$(command -v $c 2>/dev/null || echo —)"
done
echo
echo "########## G. 内核支持在线加载吗 ##########"
grep -i -E 'FPGA|DEVCFG' /boot/config-$(uname -r) 2>/dev/null | head -10 || echo "  (无 /boot/config)"
echo
echo "########## H. /root/login.py 和 tcp_speed_test.py 是什么 ##########"
head -25 /root/login.py 2>/dev/null
echo "---"
head -15 /root/tcp_speed_test.py 2>/dev/null
REMOTE
