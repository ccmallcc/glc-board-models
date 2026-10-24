#!/bin/bash
# 看清 glc2_pack 到底怎么工作：它自己知道真实长度吗？写进容器头的是什么？
cd /root/glc/pack || exit 1
D=full_img0
echo "=== 当前 hdr.txt 的 STAGE 行 ==="
grep STAGE $D/hdr.txt
echo
echo "=== 实验 1：原样跑一次，看完整输出 ==="
./glc2_pack $D /tmp/t1.glc 2>&1 | head -20
echo "  产物: $(ls -l /tmp/t1.glc 2>/dev/null | awk '{print $5}') B"
if [ -f /tmp/t1.glc ]; then
  echo -n "  容器头 4 个 STAGE 长度字段(偏移56/60/64/68): "
  od -An -tu4 --endian=big -j56 -N16 /tmp/t1.glc | tr -s ' '
fi
echo
echo "=== 实验 2：STAGE 全清零，跑一次（不迭代）==="
cp $D/hdr.txt /tmp/hdr.bak
sed -i 's/^STAGE\([0-3]\)_LEN .*/STAGE\1_LEN 0/' $D/hdr.txt
./glc2_pack $D /tmp/t2.glc 2>&1 | head -20
echo "  产物: $(ls -l /tmp/t2.glc 2>/dev/null | awk '{print $5}') B"
if [ -f /tmp/t2.glc ]; then
  echo -n "  容器头长度字段: "
  od -An -tu4 --endian=big -j56 -N16 /tmp/t2.glc | tr -s ' '
fi
echo
echo "=== 实验 3：把实验2读到的长度写回，再跑 ==="
L0=$(od -An -tu4 --endian=big -j56 -N4 /tmp/t2.glc | tr -d ' ')
L1=$(od -An -tu4 --endian=big -j60 -N4 /tmp/t2.glc | tr -d ' ')
L2=$(od -An -tu4 --endian=big -j64 -N4 /tmp/t2.glc | tr -d ' ')
L3=$(od -An -tu4 --endian=big -j68 -N4 /tmp/t2.glc | tr -d ' ')
echo "  从 t2 读到: [$L0 $L1 $L2 $L3]"
sed -i "s/^STAGE0_LEN .*/STAGE0_LEN $L0/" $D/hdr.txt
sed -i "s/^STAGE1_LEN .*/STAGE1_LEN $L1/" $D/hdr.txt
sed -i "s/^STAGE2_LEN .*/STAGE2_LEN $L2/" $D/hdr.txt
sed -i "s/^STAGE3_LEN .*/STAGE3_LEN $L3/" $D/hdr.txt
./glc2_pack $D /tmp/t3.glc 2>&1 | head -20
echo "  产物: $(ls -l /tmp/t3.glc 2>/dev/null | awk '{print $5}') B  md5=$(md5sum /tmp/t3.glc 2>/dev/null | cut -d' ' -f1)"
echo -n "  容器头长度: "; od -An -tu4 --endian=big -j56 -N16 /tmp/t3.glc | tr -s ' '
echo "  t2==t3 ? $(cmp -s /tmp/t2.glc /tmp/t3.glc && echo 相同 || echo 不同)"
echo
echo "=== 参照：p7 跑对时是 336 B / 9569311ef483fb32af337f529c87fa70 ==="
cp /tmp/hdr.bak $D/hdr.txt
echo PROBE_PACK_DONE
