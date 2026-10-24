#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""速率基准_解析.py —— 解析 A_send_session.py 的日志，出速率报告。

用法:  python3 速率基准_解析.py <session.log> [encode.log] [rc]

为什么要单独一个文件：解析规则（那几行日志的格式）是**判据**，
判据必须能**单独喂已知输入验证**——嵌在 shell 的 heredoc 里就只能等真发一次才知道对不对。
（本项目已经吃过"判据没验证过"的亏，见 07 号文 J6。）
"""
import re
import sys
import statistics

# ---- 日志行的格式（与 A_send_session.py 的 print 一一对应，改那边要同步改这里）----
# 成功: [SS]     [  1/3] IMG_0001.glc      300 B  OK  1.68 s（第 1 次）
RE_OK = re.compile(
    r'^\[SS\]\s+\[\s*(\d+)/(\d+)\]\s+(\S+)\s+(\d+) B\s+OK\s+([0-9.]+) s（第 (\d+) 次）', re.M)
# 失败: [SS]     [  2/3] IMG_0002.glc      第 1/8 次：等 ACK 超时（6.00 s）
RE_BAD = re.compile(
    r'^\[SS\]\s+\[\s*(\d+)/(\d+)\]\s+(\S+)\s+第 (\d+)/(\d+) 次：(.*?)（([0-9.]+) s）', re.M)
# 控制帧确认: [SS]   ✅ SESSION_BEGIN 已确认（第 1 次，0.22 s）
RE_ACK = re.compile(r'✅ (\S+) 已确认（第 (\d+) 次，([0-9.]+) s）')
# 控制帧重试: [SS]   SESSION_BEGIN 第 1/3 次：无应答（6.00 s）—— 4 s 后重试
RE_RETRY = re.compile(r'(\S+) 第 (\d+)/(\d+) 次：.*?—— ([0-9.]+) s 后重试')
RE_AT = re.compile(r'^\[SS\]\s+(\S+\?)\s+->\s+(.*?)\s+\[(OK|不符)\]', re.M)
RE_BLOB = re.compile(r'^\[SS\]\s+\d+\s+(\S+)\s+(\d+) B\s+([0-9a-f]{32})', re.M)
RE_DONE = re.compile(r'SESSION_DONE\s+ok=(\d+)/(\d+)')


def main():
    if len(sys.argv) < 2:
        print("用法: python3 速率基准_解析.py <session.log> [encode.log] [rc]")
        return 2
    sess = open(sys.argv[1], encoding='utf-8', errors='replace').read()
    # ★ 解析前必须先"整形"，否则会**静默丢行**（踩过一次：AT+FREQ? / AT+SYMBOL? 两行没被解析出来）。
    #   两个成因都要兜：
    #     ① 裸 CR：AT 应答里带 `\r`，而日志按 `\n` 分行 ⇒ `splitlines()` 会多切出几段。
    #     ② **续行**：应答里嵌了换行（实测日志里就有 `...MHz\n OK   [OK]`），
    #        于是 `[OK]` 被顶到下一行，正则匹配不到。
    #   做法：CR→空格；再把**不以 `[SS]` 开头的行**并回上一行。
    sess = sess.replace('\r', ' ')
    _m = []
    for _ln in sess.split('\n'):
        if _m and not _ln.startswith('[SS]'):
            _m[-1] += ' ' + _ln.strip()
        else:
            _m.append(_ln)
    sess = '\n'.join(_m)
    rc = sys.argv[3] if len(sys.argv) > 3 else '?'

    print("=" * 68)
    print(" 速率基准报告")
    print("=" * 68)
    print()

    # ---- 电台参数 ----
    print("【电台参数自检】")
    hit = False
    for m in RE_AT.finditer(sess):
        print("  %-11s %-40s [%s]" % (m.group(1), m.group(2)[:40], m.group(3)))
        hit = True
    if not hit:
        print("  （日志里没有 AT 自检行 —— 可能用了 --at-done 跳过了自检）")
    print()

    # ---- 容器 ----
    blobs = list(RE_BLOB.finditer(sess))
    if blobs:
        print("【容器】")
        for m in blobs:
            print("  %-22s %5s B  %s" % (m.group(1), m.group(2), m.group(3)[:8]))
        print()

    # ---- 每帧 ----
    frames, n_retry = [], 0
    for m in RE_OK.finditer(sess):
        frames.append(dict(seq=int(m.group(1)), name=m.group(3), size=int(m.group(4)),
                           dt=float(m.group(5)), attempt=int(m.group(6))))
    for m in RE_BAD.finditer(sess):
        n_retry += 1
        frames.append(dict(seq=int(m.group(1)), name=m.group(3), size=0,
                           dt=float(m.group(7)), attempt=int(m.group(4)),
                           fail=m.group(6).strip()))

    print("【每帧实况】")
    print("  %-4s %-22s %7s %10s %8s  %s" % ("seq", "文件", "字节", "ACK用时", "第几次", "备注"))
    print("  " + "-" * 62)
    for f in sorted(frames, key=lambda x: (x['seq'], x['attempt'])):
        note = f.get('fail') or ('★重试过' if f['attempt'] > 1 else '')
        print("  %-4d %-22s %7s %9.2f s %8d  %s"
              % (f['seq'], f['name'], f['size'] or '-', f['dt'], f['attempt'], note))
    if not frames:
        print("  （没有逐帧记录）")
    print()

    # ---- 握手 ----
    print("【握手（控制帧）】")
    hs = list(RE_ACK.finditer(sess))
    for m in hs:
        print("  %-16s 第 %s 次  %.2f s" % (m.group(1), m.group(2), float(m.group(3))))
    for m in RE_RETRY.finditer(sess):
        print("  %-16s 第 %s/%s 次失败，%s s 后重试" % (m.group(1), m.group(2), m.group(3), m.group(4)))
    if not hs and not list(RE_RETRY.finditer(sess)):
        print("  （没有握手记录）")
    print()

    for m in RE_DONE.finditer(sess):
        print("【会话结果】SESSION_DONE  ok=%s/%s" % (m.group(1), m.group(2)))
    print("【退出码】rc=%s" % rc)
    print()

    # ---- 汇总 ----
    print("=" * 68)
    ok = [f for f in frames if 'fail' not in f]
    if ok:
        dts = [f['dt'] for f in ok]
        mid = statistics.median(dts)
        data_b = sum(f['size'] for f in ok)
        data_t = sum(dts)
        print("★ 每帧 ACK 用时  中位 %.2f s   区间 %.2f ~ %.2f s   （n=%d，实测）"
              % (mid, min(dts), max(dts), len(dts)))
        print("★ 丢帧重试        %d 次（每次代价 ≈ 6 s 等 ACK + 4 s 间隔 = 10 s）" % n_retry)
        print("★ 数据段 goodput  %.0f B/s（%d B / %.1f s）"
              % (data_b / data_t if data_t else 0, data_b, data_t))
        print()
        print("  ⇒ 按此中位值：10 张 ≈ %.1f s（仅数据段，不含编码与握手）" % (mid * 10))
        print()
        if mid > 1.2:
            print("  ⇒ 每帧 >1.2 s：**建议试开 AT+SYMBOL=6（76.8 kbps）**")
            print("     （34 §4.5 说 324 B 单帧可从 1.65 s 压到约 0.5 s；代价是灵敏度/距离）")
            print("     ⚠ 两端必须同时改成一样的 SYMBOL，否则收 0 字节")
        else:
            print("  ⇒ 每帧已 <1.2 s，暂不必动 SYMBOL")
    else:
        print("★ 没有成功的帧 —— 常见原因：")
        print("   · B 端没在监听 ⇒ BEGIN 没人确认 ⇒ rc=7（最常见）")
        print("   · 电台没进透传     ⇒ rc=6")
        print("   · 两端 SYMBOL/FREQ 不一致 ⇒ 收 0 字节")
    print("=" * 68)
    return 0


if __name__ == '__main__':
    sys.exit(main())
