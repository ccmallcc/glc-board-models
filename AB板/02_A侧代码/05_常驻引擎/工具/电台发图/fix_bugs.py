#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修两个 bug：
 1) glcenc_daemon.py: do_encode 返回 3 元组，却按 4 个解包
 2) send_image.sh: 从 batch_out_cpu 拷贝时用了 *.glc 通配，
    会把上一次跑剩下的旧容器一起拷进来（实测 2 张变成 7 张）
"""
import io
import os
import re

BASE = os.path.dirname(os.path.abspath(__file__))


def patch(path, pairs):
    p = os.path.join(BASE, path)
    s = io.open(p, encoding='utf-8').read()
    for old, new, why in pairs:
        if old not in s:
            print('  !! 没找到: %s  (%s)' % (why, old[:60]))
            continue
        s = s.replace(old, new)
        print('  OK  %s' % why)
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)


print('=== glcenc_daemon.py ===')
patch('glcenc_daemon.py', [
    ("                        n, b, m, dt = do_encode(p[1], p[2], p[3])\n"
     "                        rep = 'OK %d %s %.3f' % (n, m, dt)\n"
     "                        log('[编码] %-20s %5d B  %s  %.3f s' % (p[1], n, m, dt))",
     "                        nb, md5, dt = do_encode(p[1], p[2], p[3])\n"
     "                        rep = 'OK %d %s %.3f' % (nb, md5, dt)\n"
     "                        log('[编码] %-20s %5d B  %s  %.3f s' % (p[1], nb, md5, dt))",
     'do_encode 三元组解包'),
])

print('=== send_image.sh ===')
# 两处都是同样的“拷所有 *.glc”写法，一起换成“只拷这次要的”
old_copy = ('      for f in "$BATCH_OUT"/*.glc; do\n'
            '        [ -e "$f" ] || continue\n'
            '        cp -f "$f" "$WORK/$(basename "$f")"\n'
            '      done')
new_copy = ('      # ★ 只拷这次点名要的那几张。\n'
            '      #   早先这里写的是 "$BATCH_OUT"/*.glc，会把上次剩下的旧容器一起拷进来\n'
            '      #   （实测 2 张变成 7 张），会多发图。\n'
            '      for n in $(imgs_of); do\n'
            '        [ -f "$BATCH_OUT/$n.glc" ] && cp -f "$BATCH_OUT/$n.glc" "$WORK/$n.glc"\n'
            '      done')

old_copy2 = ('        for f in "$BATCH_OUT"/*.glc; do\n'
             '          [ -e "$f" ] || continue\n'
             '          cp -f "$f" "$WORK/$(basename "$f")"\n'
             '        done')
new_copy2 = ('        for n in $(imgs_of); do\n'
             '          [ -f "$BATCH_OUT/$n.glc" ] && cp -f "$BATCH_OUT/$n.glc" "$WORK/$n.glc"\n'
             '        done')

# 跑之前先清掉本次同名旧容器，避免编失败时捡到旧的
old_pre = ('      S=$(date +%s)\n'
           '      ( cd "$GLC_DIR" && GLC_RSD_RESET=each python3 -u glc_batch_cpu.py "${ARGS[@]}" ) \\\n'
           '          > "$WORK/batch.log" 2>&1')
new_pre = ('      # ★ 先清掉本次同名的旧容器：万一这次编失败，不至于把旧容器当成本次结果\n'
           '      for n in $(imgs_of); do rm -f "$BATCH_OUT/$n.glc"; done\n'
           '      S=$(date +%s)\n'
           '      ( cd "$GLC_DIR" && GLC_RSD_RESET=each python3 -u glc_batch_cpu.py "${ARGS[@]}" ) \\\n'
           '          > "$WORK/batch.log" 2>&1')

old_pre2 = ('        ( cd "$GLC_DIR" && GLC_RSD_RESET=each python3 -u glc_batch_cpu.py "${ARGS[@]}" ) \\\n'
            '            > "$WORK/batch.log" 2>&1')
new_pre2 = ('        for n in $(imgs_of); do rm -f "$BATCH_OUT/$n.glc"; done\n'
            '        ( cd "$GLC_DIR" && GLC_RSD_RESET=each python3 -u glc_batch_cpu.py "${ARGS[@]}" ) \\\n'
            '            > "$WORK/batch.log" 2>&1')

patch('send_image.sh', [
    (old_copy, new_copy, '拷贝改为按名单（主路径）'),
    (old_copy2, new_copy2, '拷贝改为按名单（回落路径）'),
    (old_pre, new_pre, '跑前清旧容器（主路径）'),
    (old_pre2, new_pre2, '跑前清旧容器（回落路径）'),
])
print('PATCH_DONE')
