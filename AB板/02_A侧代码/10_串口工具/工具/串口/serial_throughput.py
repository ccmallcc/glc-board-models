# -*- coding: utf-8 -*-
r"""serial_throughput.py —— 实测 ttyPS0 串口的真实吞吐

做法（不需要串口登录口令）：
  PC 侧打开 COM3 收数据 ‖ 同时用 ssh（密钥）在板子上
  `head -c N /dev/zero | base64 > /dev/ttyPS0` 把数据推出去。
  板子自己打时间戳并**从 ssh 的 stdout** 返回（不占用串口）。

理论值：115200 8N1 = 11520 B/s = 11.25 KB/s
"""
import subprocess
import time

import serial

PORT = "COM3"
BAUD = 115200
KEY = r"C:\Users\ASUS\.ssh\id_board"
HOST = "root@192.168.1.2"
N_RAW = 102400          # 100 KB 原始 → base64 约 136 KB


def main():
    s = serial.Serial(PORT, BAUD, timeout=0.05)
    try:
        time.sleep(0.5)
        s.reset_input_buffer()
        print("COM3 已打开并清空缓冲")

        remote = ("S=$(date +%%s%%N); head -c %d /dev/zero | base64 > /dev/ttyPS0; "
                  "E=$(date +%%s%%N); echo \"BOARD_NS $((E-S))\"" % N_RAW)
        cmd = ["ssh", "-i", KEY, "-o", "BatchMode=yes",
               "-o", "StrictHostKeyChecking=no", HOST, remote]
        t0 = time.time()
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

        total = 0
        last = time.time()
        while True:
            c = s.read(65536)
            if c:
                total += len(c)
                last = time.time()
            if p.poll() is not None and time.time() - last > 1.5:
                break
            if time.time() - t0 > 300:
                print("超时"); break
        wall = time.time() - t0
        out = p.stdout.read().decode("utf-8", "replace").strip()

        board_ns = None
        for line in out.splitlines():
            if line.startswith("BOARD_NS"):
                board_ns = int(line.split()[1])

        expected = (N_RAW + 2) // 3 * 4          # base64 后的字节数
        print("\n板子 stdout: %s" % out[:200])
        print("PC 侧收到 %d B（期望 base64 约 %d B）" % (total, expected))
        if board_ns:
            sec = board_ns / 1e9
            print("★ 板子侧推完这段用时 %.2f s  ⇒ **%.1f KB/s**（%d B / %.2f s）"
                  % (sec, total / 1024.0 / sec, total, sec))
        print("★ PC 侧墙钟（含 ssh 启动）%.2f s ⇒ %.1f KB/s" % (wall, total / 1024.0 / wall))
        print("理论上限（115200 8N1）= 11.25 KB/s")
        print("外推：6 MB 位流 ≈ %.0f 分钟 ；248 MB 模型 ≈ %.1f 小时 ；454 MB ≈ %.1f 小时"
              % (6 * 1024 / (total / 1024.0 / max(sec, 0.001)) / 60,
                 248 * 1024 / (total / 1024.0 / max(sec, 0.001)) / 3600,
                 454 * 1024 / (total / 1024.0 / max(sec, 0.001)) / 3600))
    finally:
        s.close()
        print("\nCOM3 已关闭")
    print("SERIAL_THROUGHPUT_DONE")


if __name__ == "__main__":
    main()
