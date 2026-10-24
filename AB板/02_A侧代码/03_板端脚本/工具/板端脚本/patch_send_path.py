#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 send_image.sh 的批处理分支改成"按位流指纹自动选最快的编码路径"。"""
import io
import os

BASE = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(BASE, 'send_image.sh')
s = io.open(p, encoding='utf-8').read()

old = (
    '        echo "  --- 常驻批处理 ---"\n'
    '        for n in $(imgs_of); do rm -f "$BATCH_OUT/$n.glc"; done\n'
    '        ARGS=()\n'
    '        while IFS="$(printf \'\\t\')" read -r n p; do [ -n "${n:-}" ] && ARGS+=("$n=$p"); done < "$WORK/.manlist"\n'
    '        S=$(date +%s)\n'
    '        ( cd "$GLC_DIR" && GLC_RSD_RESET=each python3 -u glc_batch_cpu.py "${ARGS[@]}" ) \\\n'
    '            > "$WORK/batch.log" 2>&1'
)

new = (
    '        # ★ 按位流指纹自动选最快的编码路径（实测 2026-09-22，256x256）：\n'
    '        #     指纹 = 0x20260922（我们的 rans_top）⇒ glc_batch_rsd.py  PL rANS   0.714 s/张\n'
    '        #     否则                              ⇒ glc_batch_cpu.py  A53 CPU    0.894 s/张\n'
    '        #   两者容器逐字节一致（p1~p7 的 md5 全对）。\n'
    '        #   前置 speed_setup.sh：把操作数目录与 /tmp 搬进 tmpfs（单独值 ~0.3 s/张）。\n'
    '        sh /root/speed_setup.sh >/dev/null 2>&1\n'
    '        FP=$(busybox devmem 0x400C0084 32 2>/dev/null || echo "?")\n'
    '        if [ "$FP" = "0x20260922" ]; then\n'
    '          BATCH_SCRIPT=glc_batch_rsd.py; BATCH_LABEL="PL rANS（FPGA）"\n'
    '        else\n'
    '          BATCH_SCRIPT=glc_batch_cpu.py; BATCH_LABEL="A53 CPU 打包（指纹 $FP）"\n'
    '        fi\n'
    '        echo "  --- 常驻批处理：$BATCH_LABEL ---"\n'
    '        for n in $(imgs_of); do rm -f "$BATCH_OUT/$n.glc"; done\n'
    '        ARGS=()\n'
    '        while IFS="$(printf \'\\t\')" read -r n p; do [ -n "${n:-}" ] && ARGS+=("$n=$p"); done < "$WORK/.manlist"\n'
    '        S=$(date +%s)\n'
    '        ( cd "$GLC_DIR" && GLC_RSD_RESET=each python3 -u "$BATCH_SCRIPT" "${ARGS[@]}" ) \\\n'
    '            > "$WORK/batch.log" 2>&1'
)

if 'BATCH_SCRIPT' in s:
    print('  已经改过了，跳过')
elif old in s:
    s = s.replace(old, new, 1)
    print('  OK  批处理分支已改为自动选路径')
else:
    print('  !! 锚点没找到')
    raise SystemExit(3)

a = "| grep -E '就绪|单张墙钟|每张墙钟|首张|合计墙钟|^###   ' | sed 's/^/        /'"
b = "| grep -E '就绪|单张墙钟|每张墙钟|首张|合计墙钟|PL rANS 实测|^###   ' | sed 's/^/        /'"
if a in s:
    s = s.replace(a, b, 1)
    print('  OK  汇总行加上 PL rANS 实测')

c = '[ -f "$GLC_DIR/glc_batch_cpu.py" ] || { [ "$ENC_MODE" = "batch" ]'
d = '[ -f "$GLC_DIR/glc_batch_cpu.py" ] && [ -f "$GLC_DIR/glc_batch_rsd.py" ] || { [ "$ENC_MODE" = "batch" ]'
if c in s:
    s = s.replace(c, d, 1)
    print('  OK  环境自检同时要求两个脚本都在')

io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('PATCH_OK')
