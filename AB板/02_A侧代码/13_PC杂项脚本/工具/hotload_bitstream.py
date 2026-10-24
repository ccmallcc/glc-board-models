#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PC 侧一键：把 Vivado 产的 .bit 热加载进板子的 PL（**不重启、不烧卡、不用 JTAG**）。

做的事：
  1) .bit -> .bin（去头 + 32 位字字节反序，见 bit_to_bin.py）
  2) scp 到板子 /lib/firmware/
  3) 触发 /sys/class/fpga_manager/fpga0/firmware 重新配置 PL
  4) 校验 state 与 dmesg

用法：
  python hotload_bitstream.py --bit out.bit --board 192.168.1.2
  python hotload_bitstream.py --bit out.bit --board 192.168.1.2 --smoke

--smoke 会额外跑一次 S1 推理，打印 total_hard_time 供对照（约 35 秒）。

【实测 2026-09-22】接口可用；加载后 S1 total_hard_time = 346.745 ms（对照 346.753 ms）。
"""
import argparse
import os
import subprocess
import sys
import tempfile

# ⚠️ Windows 控制台默认是 GBK。脚本末尾要 print("✅ ...")，在 GBK 下会抛
#    UnicodeEncodeError: 'gbk' codec can't encode character '\u2705'
#    —— **致命且具有欺骗性**：位流其实已经加载成功了，只是最后一行打印崩了，
#    进程退出码变成 1，看日志会误判成"加载失败"。
#    修法：保留控制台编码，只把无法编码的字符替换掉（不崩、也不乱码）。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bit_to_bin import bit_to_bin  # noqa: E402

BOARD_USER = "root"
S1_DIR = "/root/glc/run/s1"
S1_JSON = "/root/glc/models/s1_encoder_ga_hyper_ZG.json"
S1_RAW = "/root/glc/models/s1_encoder_ga_hyper_ZG.raw"


def make_env(password: str):
    """Windows OpenSSH 用 SSH_ASKPASS 免交互输密码（已实测可行）。"""
    tmp = tempfile.mkdtemp(prefix="glc_askpass_")
    askpass = os.path.join(tmp, "askpass.cmd")
    with open(askpass, "w", newline="\r\n") as f:
        f.write("@echo off\r\necho %s\r\n" % password)
    env = dict(os.environ)
    env["SSH_ASKPASS"] = askpass
    env["SSH_ASKPASS_REQUIRE"] = "force"
    env["DISPLAY"] = "localhost:0"
    return env


def run(cmd, env, check=True):
    p = subprocess.run(cmd, env=env, capture_output=True, text=True, errors="replace")
    if check and p.returncode != 0:
        print("命令失败: %s" % " ".join(cmd))
        print(p.stdout)
        print(p.stderr)
        raise SystemExit(1)
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bit", required=True, help="Vivado 产的 .bit 文件")
    ap.add_argument("--board", required=True, help="板子 IP，例如 192.168.1.2")
    ap.add_argument("--password", default="fmsh", help="板端 root 密码（默认 fmsh）")
    ap.add_argument("--name", default=None, help="板上的文件名（默认取 .bit 的文件名）")
    ap.add_argument("--smoke", action="store_true", help="加载后跑一次 S1 推理做验证")
    args = ap.parse_args()

    with open(args.bit, "rb") as f:
        buf = f.read()
    try:
        fields, off, body = bit_to_bin(buf)
    except ValueError as e:
        print("转换失败: %s" % e)
        return 1

    base = args.name or os.path.basename(args.bit)
    if base.endswith(".bit"):
        base = base[:-4]
    bin_name = base + ".bin"
    bin_path = os.path.join(tempfile.mkdtemp(prefix="glc_bin_"), bin_name)
    with open(bin_path, "wb") as f:
        f.write(body)

    print("=== 1. .bit -> .bin ===")
    print("  Design : %s" % fields["a"])
    print("  Part   : %s" % fields["b"])
    print("  头 %d 字节，数据 %d 字节（头里声明 %d）" % (off, len(body), fields["e_len"]))
    print("  输出   : %s" % bin_path)

    env = make_env(args.password)
    ssh_base = [
        "ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
        "-o", "LogLevel=ERROR", "-o", "ConnectTimeout=8",
    ]
    scp_base = [
        "scp", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
        "-o", "LogLevel=ERROR",
    ]
    target = "%s@%s" % (BOARD_USER, args.board)

    print("\n=== 2. 传到板子 /lib/firmware/ ===")
    run(scp_base + [bin_path, "%s:/lib/firmware/%s" % (target, bin_name)], env)
    print("  scp 完成：/lib/firmware/%s" % bin_name)

    print("\n=== 3. 触发热加载 ===")
    p = run(
        ssh_base + [target, 'echo "%s" > /sys/class/fpga_manager/fpga0/firmware' % bin_name],
        env,
    )
    if p.stdout.strip():
        print(p.stdout)

    print("\n=== 4. 校验 ===")
    p = run(
        ssh_base + [
            target,
            'echo "state = $(cat /sys/class/fpga_manager/fpga0/state)"; dmesg | tail -3',
        ],
        env,
    )
    print(p.stdout)
    if "operating" not in p.stdout:
        print("⚠ state 不是 operating —— PL 可能没配上，重启板子可恢复")
        return 2

    if args.smoke:
        print("=== 5. 冒烟：跑一次 S1（约 35 秒）===")
        cmd = (
            "cd %s && /usr/bin/icraft-run --json %s --raw %s --input in0.ftmp "
            "--backends 'ZG330,axi://zg330aiu;Host' --log_path /tmp/pltest --log_time 2>&1 "
            "| grep -E 'total_hard_time|total_time'" % (S1_DIR, S1_JSON, S1_RAW)
        )
        p = run(ssh_base + [target, cmd], env, check=False)
        print(p.stdout)
        print("  对照：V16 记录 total_hard_time = 346.753 ms")
    else:
        print("（加 --smoke 可在加载后自动跑一次 S1 推理做验证）")

    print("\n✅ 完成：PL 已换成新位流，**未重启**。板端程序需重新启动。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
