#!/bin/bash
#=============================================================================
# speed_setup.sh —— 编码端提速的环境设置（幂等，可重复跑，已在 /etc/rc.local 里）
#
# 做什么：
#   ① 把操作数目录 pack/full_img0（含 hdr.txt）搬到 /dev/shm（tmpfs）
#   ② 把 /root/glc/run（引擎读写中间张量的地方）搬到 /dev/shm
#   ③ 把 /tmp 挂成 tmpfs
#   ④ 把 5 个子图的模型**预热进页缓存**（重启后第一张图省 ~7.8 s）
#   ⑤ 按位流指纹报告会用哪条编码路径
#
# 实测（A 板，p1~p7，引擎载入后的**每张**墙钟中位）：
#   原始单张链                 : ~12 s
#   ① 常驻引擎                  : 1.192 s
#   + ②③ tmpfs                  : 0.894 s   （打包合计 2011ms -> 804ms）
#   + PL rANS 取代 CPU 打包     : 0.712 s
#   + 关掉误导性诊断代码         : 0.700 s
#   + /root/glc/run 也进 tmpfs  : 0.678 s
#   + build_index 换 searchsorted: **0.595 s**   ← 20.2×
#   容器 md5 全程不变（p1~p7 全对）
#=============================================================================
set -u
GLC=/root/glc

echo "=== 1) 操作数目录 -> /dev/shm ==="
mkdir -p /dev/shm/glc_pack
if [ -L $GLC/pack/full_img0 ]; then
  echo "  已是软链"
else
  if [ -d $GLC/pack/full_img0 ] && [ -n "$(ls -A $GLC/pack/full_img0 2>/dev/null)" ]; then
    cp -a $GLC/pack/full_img0/. /dev/shm/glc_pack/ 2>/dev/null
  fi
  rm -rf $GLC/pack/full_img0
  ln -s /dev/shm/glc_pack $GLC/pack/full_img0
  echo "  已建立软链"
fi
# 重启后 /dev/shm 空 => 从参考模板补 hdr.txt，否则 glc_rsd_cpu 会去 ref_stage 找
if [ ! -f /dev/shm/glc_pack/hdr.txt ] && [ -f $GLC/ref_stage/pack_img0/hdr.txt ]; then
  cp -f $GLC/ref_stage/pack_img0/hdr.txt /dev/shm/glc_pack/hdr.txt
  sed -i 's/^STAGE\([0-3]\)_LEN .*/STAGE\1_LEN 0/' /dev/shm/glc_pack/hdr.txt
  echo "  已补 hdr.txt（长度清零）"
fi
ls -ld $GLC/pack/full_img0

echo
echo "=== 2) run/ -> /dev/shm（引擎的中间张量）==="
mkdir -p /dev/shm/glc_run
if [ -L $GLC/run ]; then
  echo "  已是软链"
else
  [ -d $GLC/run ] && cp -a $GLC/run/. /dev/shm/glc_run/ 2>/dev/null
  rm -rf $GLC/run
  ln -s /dev/shm/glc_run $GLC/run
  echo "  已建立软链"
fi
# 引擎要求这几个子目录存在
mkdir -p /dev/shm/glc_run/s1 /dev/shm/glc_run/s2 \
         /dev/shm/glc_run/s3p1 /dev/shm/glc_run/s3p2 /dev/shm/glc_run/s3p3
ls -ld $GLC/run

echo
echo "=== 3) /tmp -> tmpfs ==="
if mount | grep -q "tmpfs on /tmp "; then
  echo "  已是 tmpfs"
else
  mkdir -p /tmp
  mount -t tmpfs -o size=96M,mode=1777 tmpfs /tmp && echo "  已挂载 tmpfs(96M)"
fi
df -h /tmp | tail -1 | sed 's/^/  /'

echo
echo "=== 4) 预热模型进页缓存（重启后第一张图省 ~7.8 s）==="
#   实测：冷读 s1 的 157 MB 要 14.5 s（引擎载入合计），热读只要 6.7 s
#         ⇒ 差 7.8 s，就是"从 SD 卡读 5 个子图的模型"
#   页缓存是【可回收】的（内存紧张时内核会自己丢），比往 tmpfs 里拷安全得多
#   （B 端就是往 tmpfs 塞了 362 MB 不可回收内存，把 icraft 搞出 OOM 的）
# ★★ 2026-10-17 收盘改：**有常驻 daemon 时跳过这段**。
#    为什么：`start_ui.sh` 开机就在后台把 5 个子图载进 daemon，载入过程本身就把这 196 MB
#    读进页缓存了 ⇒ 这里再串行读一遍等于**白等**。实测这段占开机后约 **10~11 s**，
#    而且它挡在 `start_ui.sh` 之前（rc.local 第 30 行 vs 第 35 行）⇒ 直接把出画面推迟 10 s。
#    代价：引擎载入从 7.3 s 变 9.2 s（冷读），但那是**后台**，不挡画面也不挡 UI。
#    要老行为：GLC_WARM_MODELS=1 bash /root/speed_setup.sh
WARM=0
if [ ! -f /root/glcenc_daemon.py ] || [ "${GLC_WARM_MODELS:-0}" = "1" ]; then
for f in $GLC/models/s1_encoder_ga_hyper_ZG.raw \
         $GLC/models/s1_encoder_ga_hyper_ZG.json \
         $GLC/models/s2_hyperdec_fusion_ZG.raw \
         $GLC/models/s3_phase1_ZG.raw $GLC/models/s3_phase2_ZG.raw \
         $GLC/models/s3_phase3_ZG.raw; do
  [ -f "$f" ] || continue
  cat "$f" > /dev/null 2>&1 && WARM=$((WARM+1))
done
else
  echo "  跳过：常驻 daemon 开机就会载 5 个子图（顺带把页缓存填好），不必再串行读一遍"
  echo "        要老行为: GLC_WARM_MODELS=1 bash /root/speed_setup.sh"
fi
echo "  已预热 $WARM 个模型文件"
echo -n "  页缓存占用: "; free -m | awk 'NR==2{print $6" MB"}'

echo
echo "=== 5) 选编码路径（按位流指纹）==="
FP=$(busybox devmem 0x400C0084 32 2>/dev/null || echo "?")
echo "  +0x84 = $FP"
if [ "$FP" = "0x20260922" ]; then
  echo "  ✅ 是我们的 rans_top 位流 ⇒ 用 PL rANS（最快）"
  echo "GLC_ENC_PATH=pl"
else
  echo "  ⚠️ 不是我们的位流 ⇒ PL rANS 会被拒，回落到 A53 CPU 打包"
  echo "     想用 PL 就先热加载: echo v6.bin > /sys/class/fpga_manager/fpga0/firmware"
  echo "GLC_ENC_PATH=cpu"
fi

echo
echo "=== 6) 内存 ==="
free -m | head -2 | sed 's/^/  /'
echo SPEED_SETUP_DONE
