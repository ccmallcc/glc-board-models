#!/bin/bash
# 上板侦察：板子上到底有没有 Icraft runtime / NPU 驱动 / 设备节点。
PASS=fmsh
SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
$SSH root@192.168.0.2 'bash -s' <<'REMOTE'
echo "########## A. 系统 ##########"
uname -a
(lsb_release -a 2>/dev/null || cat /etc/os-release | head -3)
echo "内存: $(free -h | awk '/Mem:/{print $2" total, "$7" avail"}')"
echo "根分区: $(df -h / | awk 'NR==2{print $2" total, "$4" avail ("$5" used)"}')"
echo

echo "########## B. Icraft 装了吗 ##########"
echo "--- dpkg ---"
dpkg -l 2>/dev/null | grep -i -E 'icraft|customop|fmsh|fpaiz' || echo "  (dpkg 里没有任何 icraft/customop 包)"
echo "--- 可执行文件 ---"
for c in icraft icraft-run icraft-profile icraft-show icraft-model icraft_utils; do
  p=$(command -v $c 2>/dev/null); printf '  %-16s %s\n' "$c" "${p:-—}"
done
echo "--- 库 ---"
ls /usr/lib/aarch64-linux-gnu/ 2>/dev/null | grep -i -E 'icraft|zg330|buyi|aiu' || echo "  (无 icraft 库)"
echo "--- 头文件 ---"
ls /usr/include 2>/dev/null | grep -i -E 'icraft|xir' || echo "  (无 icraft 头文件)"
echo

echo "########## C. NPU 设备节点 / 驱动 ##########"
echo "--- /dev ---"
ls /dev | grep -i -E 'npu|zg|icore|aiu|devmm|etm|dri' || echo "  (无相关节点)"
echo "--- /proc/devices ---"
grep -i -E 'npu|zg|icore|aiu' /proc/devices || echo "  (无相关字符/块设备)"
echo "--- 内核模块 ---"
lsmod 2>/dev/null | grep -i -E 'npu|zg|icore|aiu|fmsh|icraft' || echo "  (没加载相关模块)"
echo "--- /lib/modules ---"
ls /lib/modules/$(uname -r)/ 2>/dev/null | head
echo "--- 内核里搜 ko ---"
find /lib/modules -name '*.ko' 2>/dev/null | grep -i -E 'npu|zg|icore|aiu' | head || echo "  (没有 npu 相关 .ko)"
echo

echo "########## D. 有没有正在跑的 NPU 服务 ##########"
ps aux 2>/dev/null | grep -i -E 'icraft|haps|zg330|npu' | grep -v grep || echo "  (没有相关进程)"
echo

echo "########## E. 板子上现有的示例 / 素材 ##########"
ls -la /root/ 2>/dev/null
echo "--- /home ---"; ls -la /home/ 2>/dev/null
echo "--- 找 imodel / ZG 产物 ---"
find / -xdev \( -name '*_ZG.json' -o -name '*_ZG.raw' -o -name '*.imodel' \) 2>/dev/null | head -10 || true
echo "--- 找 deb 包 ---"
find / -xdev -name '*.deb' 2>/dev/null | head -10 || true
echo

echo "########## F. 网络 / 服务端口 ##########"
(netstat -tlnp 2>/dev/null || ss -tlnp 2>/dev/null) | head -15
REMOTE
