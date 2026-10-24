#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单元测试_raw256入口.py —— 验证 glcenc_daemon.prepare(mode='raw256') 与 crop 模式逐字节等价

为什么要有它
------------
`raw256` 是给**工业相机用 ROI 直接出 256×256** 准备的入口（见 `82_MV-CE013-50GC接入预研_20261018.md`）：
它跳过 JPEG 解码和 LANCZOS，预处理只剩归一化（~5 ms，而 fit 模式 289 ms）。

但它必须证明一件事：**同一个 256×256 RGB 像素，走 raw256 和走 crop 得到的张量完全相同**。
否则"换了相机"就会悄悄改掉编码输入 ⇒ 所有容器 md5 基线失效。

判据（每条都要能失败）
--------------------
  T1 同图 crop 的像素 → 写成裸 RGB8 → raw256 张量 **逐元素完全相同**（bit-identical）
  T2 raw256 张量的数值范围在 [-1,1]，且 dtype=float32、shape=(1,256,256,3)
  T3 文件尺寸不对（少 1 字节）时 **必须报错**，不许静默截断/补零
  T4 raw256 比 fit 快（同一张图，各跑 3 次取最小）—— 只报数，不作为通过条件
  T5 raw256 路径**不 import PIL**（用 sys.modules 检查）

用法：python3 单元测试_raw256入口.py
退出码：0 全过；1 有失败
"""
import io
import os
import shutil
import sys
import tempfile
import time

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '电台发图'))

import glcenc_daemon as D                                          # noqa: E402

FAILS = []
TMP = tempfile.mkdtemp(prefix='glcraw_')


def check(name, cond, detail=''):
    print(('  ✅ ' if cond else '  ❌ ') + name + (('   ' + detail) if detail else ''))
    if not cond:
        FAILS.append(name)


def main():
    # ---- 造一张 640x480 的合成图（不依赖仓库里的素材）----
    w, h = 640, 480
    yy, xx = np.mgrid[0:h, 0:w]
    rgb = np.stack([(xx * 255 // (w - 1)), (yy * 255 // (h - 1)),
                    ((xx + yy) * 255 // (w + h - 2))], axis=2).astype(np.uint8)
    jpg = os.path.join(TMP, 'in.jpg')
    Image.fromarray(rgb).save(jpg, quality=92)
    print('合成输入: %s  %dx%d' % (jpg, w, h))

    # ---- T1：crop 的像素写成裸 RGB8，两条路的张量必须完全相同 ----
    t_crop, _ = D.prepare(jpg, 'crop')              # crop = 不缩放，中心取 256x256
    im = Image.open(jpg).convert('RGB')
    px = im.crop(((w - 256) // 2, (h - 256) // 2,
                  (w - 256) // 2 + 256, (h - 256) // 2 + 256))
    raw = os.path.join(TMP, 'frame.raw')
    px.tobytes() and open(raw, 'wb').write(px.tobytes())
    t_raw, prev = D.prepare(raw, 'raw256')
    check('T1 raw256 与 crop 张量逐元素完全相同',
          t_crop.shape == t_raw.shape and np.array_equal(t_crop, t_raw),
          'shape=%s  max|diff|=%.3g' % (t_raw.shape, float(np.abs(t_crop - t_raw).max())))
    check('T1b raw256 不返回预览图', prev is None)

    # ---- T2：形状/类型/范围 ----
    check('T2 shape/dtype', t_raw.shape == (1, 256, 256, 3) and t_raw.dtype == np.float32,
          '%s %s' % (t_raw.shape, t_raw.dtype))
    check('T2b 数值落在 [-1,1]', float(t_raw.min()) >= -1.0 and float(t_raw.max()) <= 1.0,
          'min=%.4f max=%.4f' % (t_raw.min(), t_raw.max()))

    # ---- T3：尺寸不对必须报错（少 1 字节）----
    bad = os.path.join(TMP, 'bad.raw')
    with open(raw, 'rb') as f:
        data = f.read()
    with open(bad, 'wb') as f:
        f.write(data[:-1])
    raised = ''
    try:
        D.prepare(bad, 'raw256')
    except RuntimeError as e:
        raised = str(e)[:60]
    check('T3 少 1 字节时报错（不静默截断）', 'raw256' in raised, raised or '没报错！')

    # ---- T4：耗时对比（只报数）----
    def tmin(mode, n=3):
        best = 1e9
        for _ in range(n):
            t0 = time.perf_counter()
            D.prepare(raw if mode == 'raw256' else jpg, mode)
            best = min(best, time.perf_counter() - t0)
        return best * 1000.0

    a, b = tmin('fit'), tmin('raw256')
    print('  ⏱  fit=%.1f ms   raw256=%.1f ms   （同一张图，各 3 次取最小）' % (a, b))

    # ---- T5：raw256 不 import PIL ----
    #   在子进程里做才准（本进程前面已经用过 PIL 了）
    probe = os.path.join(TMP, 'probe.py')
    io.open(probe, 'w', encoding='utf-8').write(
        'import sys, os\n'
        'sys.path.insert(0, %r)\n'
        'import glcenc_daemon as D\n'
        'D.prepare(%r, "raw256")\n'
        'print("PIL" in sys.modules and "IMPORTED" or "NOT_IMPORTED")\n'
        % (os.path.join(HERE, '..', '电台发图'), raw))
    import subprocess
    out = subprocess.run([sys.executable, probe], capture_output=True, text=True,
                         encoding='utf-8', errors='replace').stdout
    check('T5 raw256 路径不 import PIL', 'NOT_IMPORTED' in out, out.strip()[-30:])

    print('\n' + '=' * 60)
    if FAILS:
        print('失败 %d 条：%s' % (len(FAILS), ' / '.join(FAILS)))
        return 1
    print('全部通过 ✅  （raw256 与 crop 逐字节等价；预处理 %.1f ms → %.1f ms）' % (a, b))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
