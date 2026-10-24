#!/bin/bash
# 决定性对照：同一份 p7 输入，再单张跑一次，看是 336B/9569311e 还是 340B/d9bdae5b
cd /root/glc || exit 1
echo "=== 输入张量 ==="
md5sum /root/glc/inputs_photo/p7.ftmp
echo "=== 跑前 hdr.txt ==="
grep STAGE pack/full_img0/hdr.txt
echo
echo "=== 单张 p7 ==="
python3 -u glc_batch_cpu.py p7=/root/glc/inputs_photo/p7.ftmp > /tmp/p7again.log 2>&1
echo "rc=$?"
tr -d '\033' < /tmp/p7again.log | sed 's/\[2K//g' | grep -E 'CPU glc2_pack|容器 |md5=|墙钟|首次真开'
echo
echo "=== 跑后的操作数 md5（用于跨次比对是否同数据）==="
md5sum pack/full_img0/p0_sym.i32 pack/full_img0/p1_sym.i32 pack/full_img0/p2_sym.i32 pack/full_img0/p3_sym.i32
md5sum pack/full_img0/p0_scales.f32 pack/full_img0/p3_scales.f32
md5sum pack/full_img0/z_indices.i32
echo
echo "=== 跑后 hdr.txt ==="
grep STAGE pack/full_img0/hdr.txt
echo "=== 产出 ==="
md5sum pack/full_img0.glc
ls -l pack/full_img0.glc
echo "  参照: 336 B / 9569311ef483fb32af337f529c87fa70  (=对)   或 340 B / d9bdae5bb357ce64fb1f466e08bcf8f6 (=错)"
echo P7_AGAIN_DONE
