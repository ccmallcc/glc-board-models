#!/bin/bash
# 冒烟：把 1 个子图 + 输入传到板子，在板上用「本地 AXI 设备」跑 NPU
# 目的：验证 ① 传输速率 ② 本地设备能开 ③ 不需要 icraft-serve / 不需要网络参与推理
set -u
BOARD=192.168.31.72
PASS=fmsh
SRC=/mnt/e/fudanwei/工作区/compile_real/s3p1_int8/gen
IN=/mnt/e/fudanwei/工作区/_verify_npu/zg_int8/run_s3p1
B=/root/glc/s3p1

SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=8"
SCP="sshpass -p $PASS scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"

echo "########## 1. 建目录 ##########"
$SSH root@$BOARD "mkdir -p $B/logs && echo '  ok: '$B"

echo
echo "########## 2. 传输（计时）##########"
mkdir -p /tmp/glc_smoke
cp "$SRC/s3_phase1_ZG.json" /tmp/glc_smoke/
cp "$SRC/s3_phase1_ZG.raw"  /tmp/glc_smoke/
cp "$IN/in0.ftmp" "$IN/in1.ftmp" /tmp/glc_smoke/
ls -l /tmp/glc_smoke/ | sed 's/^/    /'
TOT=$(du -sb /tmp/glc_smoke | cut -f1)
echo "  总计 $TOT 字节"
S=$(date +%s.%N)
$SCP /tmp/glc_smoke/* root@$BOARD:$B/ 2>&1 | grep -v "^$" | sed 's/^/    /'
E=$(date +%s.%N)
D=$(echo "$E - $S" | bc)
echo "  耗时 ${D}s  ->  $(echo "scale=2; $TOT/1048576/$D" | bc) MB/s"

echo
echo "########## 3. md5 校验 ##########"
for f in s3_phase1_ZG.json s3_phase1_ZG.raw in0.ftmp in1.ftmp; do
  L=$(md5sum /tmp/glc_smoke/$f | cut -d' ' -f1)
  R=$($SSH root@$BOARD "md5sum $B/$f 2>/dev/null | cut -d' ' -f1")
  [ "$L" = "$R" ] && echo "    ✅ $f  $L" || echo "    ❌ $f  本地=$L 板上=$R"
done

echo
echo "########## 4. 板上本地 NPU 试跑（无 icraft-serve）##########"
$SSH root@$BOARD "bash -s" <<REMOTE
cd $B
echo "  --- 确认没有 icraft-serve 在跑 ---"
ps aux | grep -v grep | grep icraft-serve || echo "    (没有 icraft-serve —— 好事，证明这条路不靠它)"
echo
echo "  --- 第 1 遍：--log_io 拿 runtime v_id ---"
/usr/bin/icraft-run --json s3_phase1_ZG.json --raw s3_phase1_ZG.raw \\
  --input "in0.ftmp;in1.ftmp" --backends 'ZG330,axi://zg330aiu;Host' \\
  --log_path logs --log_io 2>&1 | tail -30
echo
echo "  --- Output 行里的 v_id ---"
grep -h "Output" logs/*_run_io.log 2>/dev/null | head -5 | sed 's/^/    /'
REMOTE
