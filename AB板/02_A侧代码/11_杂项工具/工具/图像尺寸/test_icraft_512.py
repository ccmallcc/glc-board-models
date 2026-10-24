# -*- coding: utf-8 -*-
r"""决定性测试：icraft 能不能编译【真正的 512 版】ONNX？

上次崩是因为拿了 256 版的 ONNX 却传 1,32,32,256 的参数（参数与模型不匹配）。
这次 onnx/c1_512 里的 ONNX 本身就是按 size=512 导出的，参数应当匹配。

测两个关键子图：
  s1：输入 (1,512,512,3)   —— 编码器
  s4：输入 (1,32,32,256)   —— 生成器（这里是 "16x16" -> "32x32"）

只跑 parse（第一步），过了就说明形状这关通了。
"""
import os
import subprocess
import sys

BIN = r"E:\fudanwei\Icraft-3.36.1\bin"
SRC = r"E:\fudanwei\工作区\onnx\c1_512"
OUT = r"E:\fudanwei\工作区\parse_test\c1_512"

CASES = [
    # (name, onnx文件, icraft --inputs, 输入通道数C)
    ("s1_encoder_ga_hyper", "s1_encoder_ga_hyper.onnx", "1,512,512,3", 3),
    ("s2_hyperdec_fusion", "s2_hyperdec_fusion.onnx", "1,8,8,256", 256),
    ("s3_phase1", "s3_phase1.onnx", "1,32,32,256", 256),
    ("s4_gs_generator", "s4_gs_generator.onnx", "1,32,32,256", 256),
]


def run(name, fname, shape, C):
    src = os.path.join(SRC, fname)
    out = os.path.join(OUT, name)
    os.makedirs(out, exist_ok=True)
    print('=' * 78)
    print('  %s    --inputs %s' % (name, shape))
    print('=' * 78)
    if not os.path.exists(src):
        print('  !! 缺 %s' % src)
        return None
    cmd = [os.path.join(BIN, 'icraft-parse.exe'),
           '--net_name', name, '--network', src, '--jr_path', out,
           '--log_path', os.path.join(out, 'plog'),
           '--framework', 'ONNX', '--frame_version', 'opset17', '--target', 'zhuge',
           '--inputs_dtype', 'FP32', '--inputs', shape, '--inputs_layout', 'NHWC',
           '--pre_method', 'nop',
           '--pre_scale', ','.join(['1.0'] * C),
           '--pre_mean', ','.join(['0.0'] * C),
           '--channel_swap', ','.join(str(i) for i in range(C))]
    p = subprocess.run(cmd, capture_output=True)
    txt = p.stdout.decode('utf-8', 'replace') + p.stderr.decode('utf-8', 'replace')
    pj = os.path.join(out, name + '_parsed.json')
    ok = os.path.exists(pj)
    print('  rc=%d   parsed.json: %s' % (p.returncode, '**有 ✅**' if ok else '无 ❌'))
    if not ok:
        # 打出最像错误的那几行
        keys = ('error', 'Error', 'Exception', 'fail', 'not same', 'beyond', 'support')
        hits = [l.strip() for l in txt.splitlines()
                if any(k in l for k in keys) and l.strip()]
        for l in hits[-8:]:
            print('      ' + l[:150])
    else:
        import json
        j = json.load(open(pj, encoding='utf-8'))
        ops = j.get('ops', [])
        print('      算子数 %d   params_bytes %s' % (len(ops), j.get('params_bytes')))
    print()
    return ok


print()
print('#' * 78)
print('#  icraft-parse 实测：真正的 512 版 ONNX（size=512, latent 32x32）')
print('#' * 78)
print()
res = {}
for name, fname, shape, C in CASES:
    res[name] = run(name, fname, shape, C)

print('=' * 78)
print('  汇总')
print('=' * 78)
for k, v in res.items():
    print('  %-24s %s' % (k, '✅ parse 通过' if v else '❌ 失败'))
print()
if all(res.values()):
    print('  ==> ✅✅ **512 版全部 parse 通过 ⇒ 形状这关通了，可以进五步流水线**')
elif any(res.values()):
    print('  ==> ⚠️ 部分通过，要看是哪个子图卡住')
else:
    print('  ==> ❌ 全部失败 —— icraft 不吃 512 的形状')
print('ICRAFT_512_DONE')
