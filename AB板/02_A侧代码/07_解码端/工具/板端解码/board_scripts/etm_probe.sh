#!/bin/bash
# collect the ZG330Backend memory-plan logs and the etm budget (ASCII only)
echo "===== find .icraft logs ====="
find /root -maxdepth 5 -type d -name ".icraft" 2>/dev/null | head
find /root -maxdepth 6 -path "*/.icraft/logs/*" -type f 2>/dev/null | head -20
echo
echo "===== biggest / newest zg330 logs ====="
ls -lS $(find /root -maxdepth 6 -path "*/.icraft/logs/*" -type f 2>/dev/null) 2>/dev/null | head -12
echo
echo "===== grep etm / memchunk / physical addr in those logs ====="
for f in $(find /root -maxdepth 6 -path "*/.icraft/logs/*" -type f 2>/dev/null | head -6); do
  echo "--- $f  ($(stat -c%s $f) B) ---"
  grep -a -i -m 25 -E "etm|memchunk|phy|segment|size|reuse|ocm" "$f" | head -25
  echo
done
echo "===== device tree / driver: etm or npu reserved memory ====="
ls /proc/device-tree/ 2>/dev/null | head -30
for n in etm npu zg330 aiu; do
  d=$(find /proc/device-tree -maxdepth 3 -iname "*$n*" 2>/dev/null | head -3)
  [ -n "$d" ] && echo "  $n -> $d"
done
cat /proc/iomem 2>/dev/null | grep -i -E "npu|etm|zg|aiu|reserved" | head -12
echo ETMLOG_DONE
