#!/bin/bash
# 单张图三种模式端到端耗时（--dry，不占电台）
echo "############ 单张图（p6.jpg）三种模式 ############"
for m in daemon batch single; do
  if [ "$m" = "daemon" ]; then
    python3 /root/glcenc_daemon.py status >/dev/null 2>&1 || {
      echo "  [预热] 起守护进程…"
      python3 /root/glcenc_daemon.py start
      for k in $(seq 1 60); do python3 /root/glcenc_client.py PING 2>/dev/null | grep -q PONG && break; sleep 1; done
    }
  fi
  S=$(date +%s)
  OUT=$(bash /root/send_image.sh --dry --$m /root/photo/p6.jpg 2>&1)
  E=$(date +%s)
  MD5=$(echo "$OUT" | grep -oE 'md5=[0-9a-f]+' | head -1)
  echo "  --$m :  $((E-S)) s   $MD5"
done

echo
echo "############ 守护进程热态：连发 3 张，看每张增量 ############"
for i in 1 2 3; do
  R=$(python3 /root/glcenc_client.py ENC hot$i /root/glc/inputs_photo/p$i.ftmp /root/enc_out/hot$i.glc)
  echo "  [$i] $R"
done
echo
echo "  对照（单张链参照值）:"
echo "    p1 c963bebf706c034bdbbc5cc4328dd7f9 328B / p2 6a8781ab4b78a7bc95b3e613bc603794 332B / p3 ee1a9fb4ce838512cf077aadf8bca239 320B"
md5sum /root/enc_out/hot1.glc /root/enc_out/hot2.glc /root/enc_out/hot3.glc
echo SINGLE_TIMING_DONE
