#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fake_frames.py —— 假图源：往 /dev/shm 写测试图案，用来在不接相机时验证显示链路

写的东西与 gige_grab.py 完全一致（同路径同格式），所以 gige_shim.py 分不出来：
    /dev/shm/gigecam.bin   256x256x3 RGB
    /dev/shm/gigecam.meta  "<w> <h> <seq> <ts>"

图案：左右移动的彩色竖条 + 每秒一次闪白，便于肉眼确认"画面在动、帧率正常"。

用法：python3 fake_frames.py [--fps 10] [--sec 0]   # --sec 0 = 一直跑
"""
import os
import sys
import time

import numpy as np

BIN = '/dev/shm/gigecam.bin'
META = '/dev/shm/gigecam.meta'
W = H = 256


def main():
    fps = float(sys.argv[sys.argv.index('--fps') + 1]) if '--fps' in sys.argv else 10.0
    sec = float(sys.argv[sys.argv.index('--sec') + 1]) if '--sec' in sys.argv else 0.0
    period = 1.0 / fps
    seq = 0
    t0 = time.time()
    x = np.arange(W)
    y = np.arange(H)[:, None]
    print('假图源启动 %dx%d @ %.1f fps' % (W, H, fps), flush=True)
    try:
        while True:
            seq += 1
            shift = (seq * 3) % W
            # 彩色竖条（R/G/B 三通道相位不同）+ 横向渐变
            r = ((x + shift) % 64) * 4
            g = ((x + shift * 2) % 96) * 2
            b = ((x + shift * 3) % 128) * 2
            frame = np.empty((H, W, 3), dtype=np.uint8)
            frame[:, :, 0] = (r[None, :] + (y // 4)) % 256
            frame[:, :, 1] = (g[None, :] + (y // 8)) % 256
            frame[:, :, 2] = b[None, :]
            # 每秒整闪一下白（肉眼确认帧在刷新）
            if int(time.time() - t0) != int(time.time() - t0 - period) and int(time.time()) % 2 == 0:
                if (time.time() - t0) % 1.0 < period:
                    frame[:] = 240
            tmp = BIN + '.tmp'
            with open(tmp, 'wb') as f:
                f.write(frame.tobytes())
            os.replace(tmp, BIN)
            with open(META + '.tmp', 'w') as f:
                f.write('%d %d %d %.3f\n' % (W, H, seq, time.time()))
            os.replace(META + '.tmp', META)
            if sec and (time.time() - t0) >= sec:
                break
            time.sleep(period)
    except KeyboardInterrupt:
        pass
    print('假图源结束，共 %d 帧' % seq, flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
