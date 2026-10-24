#!/bin/bash
# 板子侦察 v2：Icraft runtime / NPU 驱动 / Python 环境 / /home/work
PASS=fmsh
SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
$SSH root@192.168.0.2 'bash -s' <<'REMOTE'
echo "########## 0. 系统 ##########"
uname -a; grep -m1 'model name' /proc/cpuinfo 2>/dev/null; nproc
echo "根分区: $(df -h / | awk 'NR==2{print $2" 总 / "$4" 可用"}')"
echo

echo "########## 1. Icraft runtime ##########"
echo "--- dpkg ---"
dpkg -l 2>/dev/null | grep -i -E 'icraft|customop' || echo "  (无)"
echo "--- 命令 ---"
for c in icraft icraft-run icraft-profile icraft-show; do
  p=$(command -v $c 2>/dev/null); printf '  %-14s %s\n' "$c" "${p:-—}"
done
echo "--- 库 ---"
ls /usr/lib/aarch64-linux-gnu/ 2>/dev/null | grep -i -E 'icraft|zg330|buyi|aiu' || echo "  (无)"
echo "--- 头文件 ---"
ls /usr/include 2>/dev/null | grep -i -E 'icraft|xir' || echo "  (无)"
echo

echo "########## 2. NPU 设备节点 / 驱动 ##########"
echo "--- /dev ---"; ls /dev | grep -i -E 'npu|zg|icore|aiu|devmm|etm' || echo "  (无相关节点)"
echo "--- /proc/devices ---"; grep -i -E 'npu|zg|icore|aiu' /proc/devices || echo "  (无)"
echo "--- lsmod ---"; lsmod 2>/dev/null | grep -i -E 'npu|zg|icore|aiu|fmsh' || echo "  (无相关模块)"
echo "--- dmesg 里的 npu/zg ---"
dmesg 2>/dev/null | grep -i -E 'npu|zg330|icore|aiu' | tail -15 || echo "  (读不到 dmesg)"
echo "--- /sys 里找 ---"
ls /sys/class/ 2>/dev/null | grep -i -E 'npu|zg|icore|aiu' || echo "  (无)"
echo "--- 全部 .ko ---"
find /lib/modules -name '*.ko' 2>/dev/null | head -20
echo "--- 内存映射设备 ---"
ls -l /dev/mem /dev/udmabuf* 2>/dev/null || true
echo

echo "########## 3. 进程 / 端口 ##########"
ps aux 2>/dev/null | grep -i -E 'icraft|haps|zg330|npu' | grep -v grep || echo "  (无相关进程)"
(netstat -tlnp 2>/dev/null || ss -tlnp 2>/dev/null) | head -15
echo

echo "########## 4. Python 环境 ##########"
echo "--- 版本 ---"
for p in python3 python python3.8; do
  v=$(command -v $p 2>/dev/null) && printf '  %-10s %s  -> %s\n' "$p" "$v" "$($p --version 2>&1)"
done
echo "--- pip 包（找 icraft/numpy/torch 相关）---"
(python3 -m pip list 2>/dev/null || pip3 list 2>/dev/null || pip list 2>/dev/null) | head -40
echo "--- site-packages 里的 icraft/npu .so ---"
find /usr/lib/python3* /usr/local/lib/python3* -maxdepth 3 -name '*.so' 2>/dev/null | grep -i -E 'icraft|zg330|buyi|aiu|npu' || echo "  (无)"
echo "--- 直接试 import ---"
for m in icraft zg330backend buyibackend xir xrt numpy; do
  r=$(python3 -c "import $m; print('OK', getattr($m,'__file__','builtin'))" 2>&1 | head -1)
  printf '  import %-14s %s\n' "$m" "$r"
done
echo

echo "########## 5. /home/work ##########"
ls -la /home/ 2>/dev/null
echo "--- /home/work ---"
ls -la /home/work 2>/dev/null || echo "  (/home/work 不存在)"
echo

echo "########## 6. 全盘找 NPU 相关素材 ##########"
find / -xdev \( -name '*_ZG.json' -o -name '*_ZG.raw' -o -name '*.imodel' -o -name 'icraft*.deb' \) 2>/dev/null | head -15
echo "--- 找 python 的 npu/icraft 示例 ---"
find /home /root /opt /usr/local -maxdepth 4 -name '*.py' 2>/dev/null | head -25
REMOTE
