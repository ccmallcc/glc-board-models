#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""剥掉 icraft 日志里的进度控制字符，露出真实报错"""
import re
import sys

p = sys.argv[1] if len(sys.argv) > 1 else \
    r"E:\fudanwei\工作区\compile3\s4_int8_real\quantize.txt"
b = open(p, 'rb').read()
print("  文件大小 = %d B" % len(b))

t = b.replace(b'\x1b[2K', b'').replace(b'\x1b', b'')
t = re.sub(rb'\[[0-9;]*[A-Za-z]', b'', t)
s = None
for enc in ('utf-8', 'gbk'):
    try:
        s = t.decode(enc, 'replace')
        print("  解码方式 = %s" % enc)
        break
    except Exception:
        pass

lines = [l.strip() for l in s.split('\n') if l.strip()]
print("  总行数（剥控制符后）= %d" % len(lines))
print("\n=== 最后 30 行 ===")
for l in lines[-30:]:
    print("    " + l[:200])

print("\n=== 含错误关键字的行 ===")
kw = re.compile(r'error|Error|ERROR|fail|Fail|FAIL|Traceback|Exception|abort|fatal'
                r'|cannot|unable|No such|not found|invalid|Invalid|bad|Bad|overflow|Overflow')
hit = [l for l in lines if kw.search(l) and 'GetConsoleMode' not in l]
print("  命中 %d 行" % len(hit))
for l in hit[-20:]:
    print("    " + l[:220])
