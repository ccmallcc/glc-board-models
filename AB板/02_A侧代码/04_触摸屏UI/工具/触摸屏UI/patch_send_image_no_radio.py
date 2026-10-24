#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""patch_send_image_no_radio.py —— 给 send_image.sh 加一个"没电台也能跑编码"的开关

为什么需要：
    触摸屏 UI 的"发送"按钮要调 `send_image.sh`。但 `send_image.sh` 在 [0/3] 环境自检
    里发现没有 `/dev/ttyUSB0` 就直接 `exit 3` —— **连编码都不做**。
    本机实测 lsusb 只有 0424:2514(HUB) / 1a86:e5e3(触摸) / 0c45:6341(摄像头)，
    **CH340 电台(1a86:7523)不在**，所以 UI 上"发送"永远走不到编码。

改法（最小、向后兼容）：
    没有 /dev/ttyUSB0 时，如果 `GLC_ALLOW_NO_RADIO=1`，就不退出，改为自动 `DRY=1`
    （只编码、产出 .glc 容器、不占电台），并在日志里说清楚。
    不设这个环境变量时，行为与原来**完全一致**（exit 3）。

用法： python patch_send_image_no_radio.py <原始 send_image.sh> <输出 send_image.sh>
"""
import sys

OLD = '''if [ ! -c /dev/ttyUSB0 ]; then
  echo "!! 找不到 /dev/ttyUSB0（电台）。lsusb 应该能看到 1a86:7523"
  lsusb 2>/dev/null | head -5
  exit 3
fi
echo "  电台设备  : /dev/ttyUSB0 OK"
'''

NEW = '''if [ ! -c /dev/ttyUSB0 ]; then
  if [ "${GLC_ALLOW_NO_RADIO:-0}" = "1" ]; then
    echo "  ⚠ 没有 /dev/ttyUSB0（电台）。GLC_ALLOW_NO_RADIO=1 ⇒ 只编码不发射（自动 --dry）"
    echo "  实际 USB 设备:"
    lsusb 2>/dev/null | head -5 | sed 's/^/      /'
    DRY=1
  else
    echo "!! 找不到 /dev/ttyUSB0（电台）。lsusb 应该能看到 1a86:7523"
    lsusb 2>/dev/null | head -5
    exit 3
  fi
else
  echo "  电台设备  : /dev/ttyUSB0 OK"
fi
'''

DRYOLD = '  echo "=== --dry 指定，不发。容器在 $WORK ==="'
DRYNEW = ('  if [ "${GLC_ALLOW_NO_RADIO:-0}" = "1" ] && [ ! -c /dev/ttyUSB0 ]; then\n'
          '    echo "=== 无电台：只编码，不发。容器在 $WORK ==="\n'
          '  else\n'
          '    echo "=== --dry 指定，不发。容器在 $WORK ==="\n'
          '  fi')


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    src, dst = sys.argv[1], sys.argv[2]
    t = open(src, encoding="utf-8").read()
    n = 0
    if NEW.strip() in t:
        print("已经打过补丁，原样输出")
    elif OLD in t:
        t = t.replace(OLD, NEW, 1)
        n += 1
    else:
        raise SystemExit("!! 找不到环境自检那一段，send_image.sh 可能被改过，手动看")
    # 可选：--dry 的提示语
    if DRYNEW not in t and DRYOLD in t:
        t = t.replace(DRYOLD, DRYNEW, 1)
        n += 1
    open(dst, "w", encoding="utf-8", newline="\n").write(t)
    print("已打 %d 处补丁 -> %s" % (n, dst))
    # 自检：语法
    import subprocess
    r = subprocess.run(["bash", "-n", dst], capture_output=True, text=True)
    print("bash -n :", "OK" if r.returncode == 0 else r.stderr)


if __name__ == "__main__":
    main()
