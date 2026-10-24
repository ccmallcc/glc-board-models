# -*- coding: utf-8 -*-
r"""把切好的 512 s4 两段（a/b）走完整的 int8 编译链。

步骤：
  1) icraft-parse 两段（--inputs 要按 NHWC 给：a 是 1,32,32,256；b 是 1,128,128,512）
  2) 给 b 造标定输入：把 s4 的 8 个标定 latent 喂给 a（onnxruntime），
     拿到跨段张量，按 NHWC float32 存成 b 的 calib/<i>.ftmp（+ list.txt）
  3) c1_pipeline.py 各跑 optimize/quantize/adapt/generate（int8）

为什么 b 的标定输入必须这么造：b 的输入就是 a 的输出（跨段张量），
拿原始 latent 去标定 b 会得到完全错的数值范围 —— 量化标定错，整个 b 的精度就废了。

用法：
  python c1_split512_compile.py --stage parse
  python c1_split512_compile.py --stage calib
  python c1_split512_compile.py --stage compile --seg a
  python c1_split512_compile.py --stage compile --seg b
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np

BIN = r'E:\fudanwei\Icraft-3.36.1\bin'
SPLIT = r'E:\fudanwei\工作区\split512'
CALROOT = r'E:\fudanwei\工作区\calibref_512'
SRC_CAL = os.path.join(CALROOT, 'calib', 's4_gs_generator')
PY = r'E:\fudanwei\envs\torch_v2.0.1\python.exe'
PIPE = r'E:\fudanwei\工作区\tools\c1_pipeline.py'

SEGS = {
    'a': dict(onnx=os.path.join(SPLIT, 's4_512_a.onnx'), name='s4_512_a',
              nhwc='1,32,32,256', C=256,
              calib=SRC_CAL, list=os.path.join(SRC_CAL, 'list.txt')),
    'b': dict(onnx=os.path.join(SPLIT, 's4_512_b.onnx'), name='s4_512_b',
              nhwc='1,128,128,256', C=256,
              calib=os.path.join(CALROOT, 'calib', 's4_512_b'),
              list=os.path.join(CALROOT, 'calib', 's4_512_b', 'list.txt')),
}


def do_parse(seg):
    s = SEGS[seg]
    out = os.path.join(r'E:\fudanwei\工作区\parse512', seg)
    os.makedirs(out, exist_ok=True)
    cmd = [os.path.join(BIN, 'icraft-parse.exe'),
           '--net_name', s['name'], '--network', s['onnx'], '--jr_path', out,
           '--log_path', os.path.join(out, 'plog'),
           '--framework', 'ONNX', '--frame_version', 'opset17', '--target', 'zhuge',
           '--inputs_dtype', 'FP32', '--inputs', s['nhwc'], '--inputs_layout', 'NHWC',
           '--pre_method', 'nop',
           '--pre_scale', ','.join(['1.0'] * s['C']),
           '--pre_mean', ','.join(['0.0'] * s['C']),
           '--channel_swap', ','.join(str(i) for i in range(s['C']))]
    p = subprocess.run(cmd, capture_output=True)
    txt = (p.stdout + p.stderr).decode('utf-8', 'replace')
    pj = os.path.join(out, s['name'] + '_parsed.json')
    ok = os.path.exists(pj)
    print('parse %s rc=%d -> %s' % (seg, p.returncode, 'OK' if ok else 'FAIL'))
    if not ok:
        for l in txt.splitlines():
            if any(k in l for k in ('rror', 'xception', 'fail', 'not same', 'beyond')):
                print('   ' + l.strip()[:160])
        return False
    print('   %s  %.1f MB' % (pj, os.path.getsize(pj) / 1048576.0))
    return True


def do_calib():
    """用 a 的 ONNX 给 8 个标定 latent 求跨段张量，写成 b 的标定输入。"""
    import onnxruntime as ort
    s = SEGS['b']
    os.makedirs(s['calib'], exist_ok=True)
    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    sa = ort.InferenceSession(SEGS['a']['onnx'], so, providers=['CPUExecutionProvider'])
    names = sorted(f for f in os.listdir(SRC_CAL) if f.endswith('.ftmp'))
    lines = []
    for f in names:
        x = np.fromfile(os.path.join(SRC_CAL, f), dtype=np.float32)
        x = x.reshape(1, 32, 32, 256).transpose(0, 3, 1, 2).copy()
        mid = sa.run(None, {sa.get_inputs()[0].name: x})[0]      # (1,512,128,128) NCHW
        nhwc = np.transpose(mid, (0, 2, 3, 1)).astype(np.float32)  # (1,128,128,256)
        dst = os.path.join(s['calib'], f)
        nhwc.tofile(dst)
        lines.append(f)
        print('  %s -> %s  %d bytes  min %.2f max %.2f'
              % (f, os.path.basename(dst), os.path.getsize(dst), nhwc.min(), nhwc.max()))
    with open(s['list'], 'w', encoding='utf-8', newline='\n') as fh:
        fh.write('\n'.join(lines) + '\n')
    print('calib for b: %d samples -> %s' % (len(lines), s['calib']))
    return True


def do_compile(seg):
    s = SEGS[seg]
    pj = os.path.join(r'E:\fudanwei\工作区\parse512', seg, s['name'] + '_parsed.json')
    if not os.path.exists(pj):
        print('缺 parsed，先 --stage parse'); return False
    out = os.path.join(r'E:\fudanwei\工作区\compile512split', seg + '_int8')
    os.makedirs(out, exist_ok=True)
    cmd = [PY, PIPE, '--parsed', pj, '--dtype', 'int8', '--outdir', out,
           '--calib_dir', s['calib'], '--calib_list', s['list'],
           '--stages', 'optimize,quantize,adapt,generate']
    print('compile %s -> %s' % (seg, out)); sys.stdout.flush()
    p = subprocess.run(cmd, capture_output=True)
    print((p.stdout + p.stderr).decode('utf-8', 'replace')[-2500:])
    gen = os.path.join(out, 'gen', s['name'] + '_ZG.json')
    print('gen json: %s' % ('OK %.1f MB' % (os.path.getsize(gen) / 1048576.0) if os.path.exists(gen) else 'MISSING'))
    return os.path.exists(gen)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', required=True, choices=['parse', 'calib', 'compile'])
    ap.add_argument('--seg', default='')
    a = ap.parse_args()
    if a.stage == 'parse':
        ok = all([do_parse('a'), do_parse('b')])
    elif a.stage == 'calib':
        ok = do_calib()
    else:
        segs = [a.seg] if a.seg else ['a', 'b']
        ok = all([do_compile(s) for s in segs])
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
