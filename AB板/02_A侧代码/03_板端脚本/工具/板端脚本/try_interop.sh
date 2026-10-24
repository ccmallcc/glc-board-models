#!/bin/bash
echo "=== wsl.conf ==="
cat /etc/wsl.conf 2>/dev/null || echo "  (无)"
echo
echo "=== binfmt_misc 挂了吗 ==="
ls /proc/sys/fs/binfmt_misc/ 2>&1 | head -5
echo
echo "=== sudo 免密？ ==="
sudo -n true 2>&1 && echo "  可以免密 sudo" || echo "  需要密码"
echo
echo "=== 试挂 binfmt_misc ==="
sudo -n mount -t binfmt_misc binfmt_misc /proc/sys/fs/binfmt_misc 2>&1 | head -3
ls /proc/sys/fs/binfmt_misc/ 2>&1 | head -8
echo
echo "=== WSLInterop 注册了吗 ==="
cat /proc/sys/fs/binfmt_misc/WSLInterop 2>/dev/null || echo "  没有 WSLInterop 条目"
