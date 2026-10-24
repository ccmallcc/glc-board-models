#!/bin/bash
# v3 验证：① 预处理与 enc_image.py 逐字节一致  ② 单张耗时
cd /root
GLC=/root/glc
IN0=$GLC/run/s1/in0.ftmp

echo "############ 0) 停旧守护进程，装 v3 ############"
python3 /root/glcenc_daemon.py stop >/dev/null 2>&1
python3 /root/glcenc_daemon.py clean >/dev/null 2>&1
sleep 1
python3 -c "import ast;ast.parse(open('/root/glcenc_daemon.py',encoding='utf-8').read());print('  v3 语法 OK')"
grep -c "ENCIMG\|ENCBATCH" /root/glcenc_daemon.py | sed 's/^/  v3 含 ENCIMG\/ENCBATCH 行数: /'

echo
echo "############ 1) 起守护进程 ############"
S=$(date +%s); python3 /root/glcenc_daemon.py start; E=$(date +%s)
echo "  start 返回耗时 $((E-S)) s"
for k in $(seq 1 60); do python3 /root/glcenc_client.py PING 2>/dev/null | grep -q PONG && break; sleep 1; done
echo "  $(python3 /root/glcenc_client.py PING)   （就绪约 ${k} s）"

echo
echo "############ 2) ★ 预处理逐字节一致性 ############"
echo "--- 参照：enc_image.py ---"
python3 /root/enc_image.py /root/photo/p6.jpg --mode fit --out $IN0 2>&1 | grep -E "模式|张量|已写"
cp -f $IN0 /tmp/ref_p6.ftmp
echo "  ref  md5=$(md5sum /tmp/ref_p6.ftmp | cut -d' ' -f1)"

echo "--- 守护进程内预处理（ENCIMG）---"
R=$(python3 /root/glcenc_client.py ENCIMG p6 /root/photo/p6.jpg /root/enc_out/v3_p6.glc)
echo "  ENCIMG -> $R"
cp -f $IN0 /tmp/dae_p6.ftmp
echo "  dae  md5=$(md5sum /tmp/dae_p6.ftmp | cut -d' ' -f1)"

if cmp -s /tmp/ref_p6.ftmp /tmp/dae_p6.ftmp; then
  echo "  ✅ 输入张量逐字节一致"
else
  echo "  ❌ 输入张量不一致！差 $(cmp -l /tmp/ref_p6.ftmp /tmp/dae_p6.ftmp | wc -l) 字节"
fi

echo
echo "############ 3) 单张耗时（热态，连发 4 张不同图）############"
for n in 1 2 3 4; do
  T0=$(date +%s%N 2>/dev/null || date +%s)
  R=$(python3 /root/glcenc_client.py ENCIMG v3p$n /root/photo/p$n.jpg /root/enc_out/v3p$n.glc)
  T1=$(date +%s%N 2>/dev/null || date +%s)
  printf "  p%d  %s\n" "$n" "$R"
done

echo
echo "############ 4) 与单张链的容器对照（必须一致）############"
echo "  参照: p1 c963bebf706c034bdbbc5cc4328dd7f9 328B"
echo "        p2 6a8781ab4b78a7bc95b3e613bc603794 332B"
echo "        p3 ee1a9fb4ce838512cf077aadf8bca239 320B"
echo "        p6 198080dcb5cbbbd1bed8b5f6b23c94d8 308B"
for n in 1 2 3 6; do
  [ -f /root/enc_out/v3p$n.glc ] && printf "  实际: p%d %s %sB\n" "$n" "$(md5sum /root/enc_out/v3p$n.glc | cut -d' ' -f1)" "$(stat -c%s /root/enc_out/v3p$n.glc)"
done
[ -f /root/enc_out/v3_p6.glc ] && printf "  实际: p6(ENCIMG) %s %sB\n" "$(md5sum /root/enc_out/v3_p6.glc | cut -d' ' -f1)" "$(stat -c%s /root/enc_out/v3_p6.glc)"

echo
echo "############ 5) ENCBATCH 一次请求编 3 张 ############"
R=$(python3 /root/glcenc_client.py ENCBATCH /root/enc_out v3b4=/root/photo/p4.jpg v3b5=/root/photo/p5.jpg v3b6=/root/photo/p6.jpg)
echo "$R" | sed 's/^/  /'
echo "V3_TEST_DONE"
