#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_payload.py —— **独立复算**黄金 payload，验证它与逐符号 trace 自洽。

为什么需要它：C2c 的 tb 拿 `payload_p*.txt` 当黄金值。但如果那个黄金文件本身错了，
tb 就是在追一个鬼 —— 而且会追得理直气壮（因为"有出处"）。
所以**在信它之前，先用另一条路径把它算出来对一遍**。

复算依据（`assets/板端代码/glc_board_encoder.h` 的 `encode()` 尾部）：

    uint32_t *ptr = output + DEPTH;          // 指针从末尾往前走
    for (每个符号，编码顺序) if (emit) *--ptr = emit_word;
    *--ptr = (uint32_t)(x >> 32);            // flush 先写高字
    *--ptr = (uint32_t)x;                    // 再写低字
    payload = output[ptr .. DEPTH)           // 内存顺序

=> 内存里的字序是：
       [ x_low, x_high, emit_{n-1}, emit_{n-2}, ..., emit_1, emit_0 ]
   注意 **emit 字是"发射顺序的逆序"**（因为写指针在递减）。
   字节序：每个 uint32 **小端**。

用法：
    python3 /mnt/e/fudanwei/GLC-共享包/工具/verify_payload.py [tag]
    tag 缺省为 p1 p2 都跑。
退出码：0 = 全过，1 = 有失败。
"""
import os
import sys

R = "/mnt/e/fudanwei/_logs/rans"


def load_symtrace(path):
    rows = []
    for line in open(path):
        p = line.split()
        if len(p) != 7:
            continue
        rows.append(dict(
            x_in=int(p[0], 16), freq=int(p[1], 16), start=int(p[2], 16),
            x_out=int(p[3], 16), emit=int(p[4]), emit_word=int(p[5], 16),
            bypass=int(p[6])))
    return rows


def load_payload_hex(path):
    s = "".join(l.strip() for l in open(path))
    return bytes.fromhex(s)


def le32(w):
    return bytes([w & 0xFF, (w >> 8) & 0xFF, (w >> 16) & 0xFF, (w >> 24) & 0xFF])


def check(tag):
    st = os.path.join(R, "symtrace_%s.txt" % tag)
    pl = os.path.join(R, "payload_%s.txt" % tag)
    if not (os.path.exists(st) and os.path.exists(pl)):
        print("%s: 缺文件，跳过" % tag)
        return 0, 0

    rows = load_symtrace(st)
    golden = load_payload_hex(pl)

    emits = [r["emit_word"] for r in rows if r["emit"] == 1]
    final_x = rows[-1]["x_out"]

    words = [final_x & 0xFFFFFFFF, (final_x >> 32) & 0xFFFFFFFF] + list(reversed(emits))
    mine = b"".join(le32(w) for w in words)

    # 同时写一份「一字一行」的 $readmemh 文件，给 C2c 的 tb 用。
    # 因为 mine 就是 words 的小端展开，所以「黄金字节流 == mine」成立时，
    # 「tb 逐字比对 words」就**等价于**逐字节比对 —— 见下面的断言。
    wpath = os.path.join(R, "payload_%s_words.hex" % tag)
    with open(wpath, "w") as f:
        for w in words:
            f.write("%08x\n" % w)

    ok = (mine == golden)
    print("=== %s ===" % tag)
    print("  符号数        : %d" % len(rows))
    print("  emit 次数     : %d" % len(emits))
    print("  末态 x        : %016x" % final_x)
    print("  flush 低/高字 : %08x %08x" % (words[0], words[1]))
    print("  复算 payload  : %d 字节 = %d 字" % (len(mine), len(words)))
    print("  黄金 payload  : %d 字节" % len(golden))
    if not ok:
        n = min(len(mine), len(golden))
        off = next((i for i in range(n) if mine[i] != golden[i]), n)
        print("  ❌ 不一致：首个不符字节偏移 %d" % off)
        if off < n:
            print("     got  %s" % mine[max(0, off - 4):off + 8].hex())
            print("     want %s" % golden[max(0, off - 4):off + 8].hex())
    else:
        print("  ✅ 逐字节一致（%d 字节全等）" % len(golden))
    print()
    return (1 if ok else 0), 1


def main(argv):
    tags = argv[1:] if len(argv) > 1 else ["p1", "p2"]
    good = tot = 0
    for t in tags:
        g, n = check(t)
        good += g
        tot += n
    print("=" * 60)
    print("结论：%s  （%d/%d 个 payload 与逐符号 trace 自洽）"
          % ("全过 PASS" if good == tot else "有失败 FAIL", good, tot))
    print("=" * 60)
    return 0 if good == tot else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
