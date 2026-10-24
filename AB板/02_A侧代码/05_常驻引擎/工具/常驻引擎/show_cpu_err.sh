#!/bin/bash
# 抓 batch_cpu.log 里第一个 glc2_pack 异常的完整上下文
L=/tmp/batch_cpu.log
echo "=== 异常出现次数 ==="
grep -c "没打印全" $L
echo
echo "=== 第一次异常的完整上下文（约 30 行）==="
tr -d '\033' < $L | sed 's/\[2K//g' \
  | grep -n -A 28 "没打印全 4 个相位长度" | head -40
echo
echo "=== full_img0 目录现在有什么 ==="
ls -l /root/glc/pack/full_img0/
echo
echo "=== hdr.txt 内容 ==="
cat /root/glc/pack/full_img0/hdr.txt 2>/dev/null
echo
echo "=== 参考 hdr ==="
cat /root/glc/ref_stage/pack_img0/hdr.txt 2>/dev/null
echo SHOW_DONE
