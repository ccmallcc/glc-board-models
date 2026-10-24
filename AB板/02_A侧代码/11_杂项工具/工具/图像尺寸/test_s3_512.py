# -*- coding: utf-8 -*-
r"""补测 s3_phase1（512 版）—— 上次失败是因为它是【双输入】网络，我只传了一个输入。

icraft-parse 的 --help 写着：';' 分隔两个输入。所以：
    --inputs '1,32,32,256;1,32,32,256'
    --inputs_dtype 'FP32;FP32'
    --pre_method 'nop;nop'
    --pre_scale '...;...'   --pre_mean '...;...'   --channel_swap '...;...'

顺便把 256 版的 s3 也跑一遍做对照（确认双输入语法是对的）。
"""
import os
import subprocess
import sys

BIN = r"E:\fudanwei\Icraft-3.36.1\bin"
C = 256
PRE_S = ','.join(['1.0'] * C)
PRE_M = ','.join(['0.0'] * C)
SWAP = ','.join(str(i) for i in range(C))

CASES = [
    # (标签, onnx目录, 名字, 单输入形状, 输出目录)
    ("256 版 s3_phase1（对照，双输入）", r"E:\fudanwei\工作区\onnx\c1_simple",
     "s3_phase1", "1,16,16,256", r"E:\fudanwei\工作区\parse_test\s3_256"),
    ("512 版 s3_phase1（双输入）", r"E:\fudanwei\工作区\onnx\c1_512",
     "s3_phase1", "1,32,32,256", r"E:\fudanwei\工作区\parse_test\s3_512"),
    ("512 版 s3_phase2（双输入）", r"E:\fudanwei\工作区\onnx\c1_512",
     "s3_phase2", "1,32,32,256", r"E:\fudanwei\工作区\parse_test\s3p2_512"),
    ("512 版 s3_phase3（双输入）", r"E:\fudanwei\工作区\onnx\c1_512",
     "s3_phase3", "1,32,32,256", r"E:\fudanwei\工作区\parse_test\s3p3_512"),
]

TWO = ";".join([PRE_S, PRE_S])
TWO_M = ";".join([PRE_M, PRE_M])
TWO_SW = ";".join([SWAP, SWAP])

for tag, srcdir, name, one, out in CASES:
    src = os.path.join(srcdir, name + '.onnx')
    os.makedirs(out, exist_ok=True)
    print('=' * 78)
    print('  %s' % tag)
    print('=' * 78)
    if not os.path.exists(src):
        print('  !! 缺 %s' % src)
        print()
        continue
    cmd = [os.path.join(BIN, 'icraft-parse.exe'),
           '--net_name', name, '--network', src, '--jr_path', out,
           '--log_path', os.path.join(out, 'plog'),
           '--framework', 'ONNX', '--frame_version', 'opset17', '--target', 'zhuge',
           '--inputs_dtype', 'FP32;FP32',
           '--inputs', '%s;%s' % (one, one),
           '--inputs_layout', 'NHWC;NHWC',
           '--pre_method', 'nop;nop',
           '--pre_scale', TWO, '--pre_mean', TWO_M, '--channel_swap', TWO_SW]
    p = subprocess.run(cmd, capture_output=True)
    txt = p.stdout.decode('utf-8', 'replace') + p.stderr.decode('utf-8', 'replace')
    pj = os.path.join(out, name + '_parsed.json')
    ok = os.path.exists(pj)
    print('  rc=%d   parsed.json: %s' % (p.returncode, '**有 ✅**' if ok else '无 ❌'))
    if ok:
        import json
        j = json.load(open(pj, encoding='utf-8'))
        print('      算子数 %d   params_bytes %s' % (len(j.get('ops', [])), j.get('params_bytes')))
    else:
        keys = ('error', 'Error', 'Exception', 'fail', 'not same', 'beyond', 'support', 'require')
        for l in [x.strip() for x in txt.splitlines() if any(k in x for k in keys)][-6:]:
            print('      ' + l[:150])
    print()
print('S3_512_DONE')
