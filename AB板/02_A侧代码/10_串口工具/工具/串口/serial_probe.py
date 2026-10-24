# -*- coding: utf-8 -*-
r"""serial_probe.py —— 实测板子的串口控制台：能不能拿到 shell、带宽多少

板子：console=ttyPS0,115200n8，getty 正跑在 ttyPS0 上（ssh 实测）
本机：COM3 = Silicon Labs CP210x USB to UART Bridge（与官方手册的 CP2103GM 对得上）

阶段1（本脚本）：只听 + 敲回车，看是登录提示还是 shell 提示
阶段2（加 --run）：拿到 shell 后测真实吞吐
"""
import sys
import time

import serial

PORT = "COM3"
BAUD = 115200


def drain(s, secs, tag=""):
    t0 = time.time()
    buf = b""
    while time.time() - t0 < secs:
        chunk = s.read(4096)
        if chunk:
            buf += chunk
    if tag:
        print("--- [%s] 收到 %d B ---" % (tag, len(buf)))
        if buf:
            print(buf.decode("utf-8", "replace"))
    return buf


def main():
    run = "--run" in sys.argv
    s = serial.Serial(PORT, BAUD, timeout=0.2, bytesize=8,
                      parity=serial.PARITY_NONE, stopbits=1)
    try:
        print("已打开 %s @ %d 8N1" % (PORT, BAUD))
        time.sleep(0.5)
        drain(s, 2.0, "刚打开时残留")

        s.write(b"\r\n")
        time.sleep(1.5)
        b = drain(s, 2.5, "敲回车之后")

        txt = b.decode("utf-8", "replace")
        if "login:" in txt.lower():
            print("\n### 结论：串口上是【登录提示】，需要口令 —— 阶段1 到此")
            return
        print("\n### 结论：串口上像是【shell 提示】")

        if not run:
            print("（加 --run 测吞吐）")
            return

        print("\n=== 阶段2：测真实吞吐 ===")
        # 让板子吐一段已知大小的 base64（纯 ASCII，安全）
        for n_bytes, label in ((40960, "40 KB 原始 -> base64 约 55 KB"),
                               (204800, "200 KB 原始 -> base64 约 273 KB")):
            s.reset_input_buffer()
            cmd = ("echo __BEG__; head -c %d /dev/zero | base64; echo __END__\n" % n_bytes)
            t0 = time.time()
            s.write(cmd.encode())
            buf = b""
            while b"__END__" not in buf and time.time() - t0 < 600:
                c = s.read(65536)
                if c:
                    buf += c
            el = time.time() - t0
            i0 = buf.find(b"__BEG__")
            i1 = buf.find(b"__END__")
            payload = buf[i0 + 7:i1].replace(b"\r", b"").replace(b"\n", b"") if i0 >= 0 and i1 > i0 else b""
            print("  %-28s 用时 %6.2f s  收到 %7d B  ⇒ **%.1f KB/s**（含终端回显/换行开销）"
                  % (label, el, len(payload), len(payload) / 1024.0 / el))

        # 反向：往板子写（用 cat > /tmp/x 然后 wc -c）
        print("\n  --- 反向（PC -> 板子）---")
        blob = ("A" * 64 + "\n") * 1024          # 65 KB
        s.reset_input_buffer()
        s.write(b"cat > /tmp/serwrite.bin\n")
        time.sleep(0.5)
        t0 = time.time()
        s.write(blob.encode())
        s.write(b"\x04")                          # Ctrl-D 结束
        time.sleep(1.0)
        s.write(b"wc -c < /tmp/serwrite.bin\n")
        time.sleep(2.0)
        out = drain(s, 1.5, "反向结果")
        el = time.time() - t0
        print("  发送 %d B 用时 %.2f s ⇒ **%.1f KB/s**（反向）" % (len(blob), el, len(blob) / 1024.0 / el))
    finally:
        s.close()
        print("\nCOM3 已关闭")
    print("SERIAL_PROBE_DONE")


if __name__ == "__main__":
    main()
