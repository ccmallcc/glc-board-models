#!/bin/bash
# 三种编码模式对照测试
cd /root
echo "############ A) 守护进程 start 是否立刻返回（fd 修复验证）############"
python3 /root/glcenc_daemon.py stop >/dev/null 2>&1
sleep 1
S=$(date +%s%N 2>/dev/null || date +%s)
python3 /root/glcenc_daemon.py start
E=$(date +%s%N 2>/dev/null || date +%s)
echo "  start 返回耗时（秒）: $(( (E-S)/1000000000 ))  （>60 就说明 fd 没修好）"
echo
echo "  等引擎就绪…"
for k in $(seq 1 60); do
  python3 /root/glcenc_client.py PING 2>/dev/null | grep -q PONG && { echo "  就绪（约 $k s）"; break; }
  sleep 1
done
python3 /root/glcenc_client.py PING

echo
echo "############ B) --daemon 模式发两张（--dry，不占电台）############"
S=$(date +%s)
bash /root/send_image.sh --dry --daemon /root/photo/p6.jpg /root/photo/p2.jpg 2>&1 \
  | grep -E "编码方式|守护进程|就绪|PONG|=> |编码完成|SEND_IMAGE_DONE|OK |ERR "
E=$(date +%s)
echo "  >>> --daemon 两张总墙钟 $((E-S)) s"

echo
echo "############ C) 默认批处理模式发两张 ############"
S=$(date +%s)
bash /root/send_image.sh --dry --batch /root/photo/p6.jpg /root/photo/p2.jpg 2>&1 \
  | grep -E "编码方式|就绪|单张墙钟|每张墙钟|首张|=> |编码完成|SEND_IMAGE_DONE"
E=$(date +%s)
echo "  >>> --batch 两张总墙钟 $((E-S)) s"

echo
echo "############ D) 单张链模式发一张（对照）############"
S=$(date +%s)
bash /root/send_image.sh --dry --single /root/photo/p6.jpg 2>&1 \
  | grep -E "编码方式|=> |编码完成|SEND_IMAGE_DONE|rc="
E=$(date +%s)
echo "  >>> --single 一张总墙钟 $((E-S)) s"

echo
echo "############ E) 停止守护进程 ############"
python3 /root/glcenc_daemon.py stop
python3 /root/glcenc_daemon.py status
echo MODE_TEST_DONE
