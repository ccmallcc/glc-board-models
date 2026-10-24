#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单元测试_prepare回归.py —— 证明 prepare() 参数化后，**256 下与板上那版逐字节等价**

为什么要有它
------------
2026-10-18 把 `glcenc_daemon.prepare()` 的目标边长改成由 `GLC_SIZE` 决定（默认 256）。
这是**板上正在跑的预处理路径**，改错一个像素，容器 md5 就全变。

判据：拿**板上那一版**（`工具/_历史_板端文件/glcenc_daemon.4f51fd3d.py`，md5 与板上一致）
和新版，对同一张图跑三种 mode，**张量必须逐元素完全相同**。

  T1 fit     新旧张量相同
  T2 crop    新旧张量相同
  T3 squash  新旧张量相同
  T4 raw256  ：**旧版（65e1d86）还没有这个模式**，无从比较 ⇒ 跳过并说明
  T5 新版在 256 下的张量形状 = (1,256,256,3)

用法：python3 单元测试_prepare回归.py
退出码 0 全过 / 1 有失败
"""
import importlib.util
import os
import shutil
import sys
import tempfile

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
NEW = os.path.join(REPO, '工具', '电台发图', 'glcenc_daemon.py')
OLD = os.path.join(REPO, '工具', '_历史_板端文件', 'glcenc_daemon.4f51fd3d.py')

FAILS = []


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def check(name, cond, detail=''):
    print(('  ✅ ' if cond else '  ❌ ') + name + (('   ' + detail) if detail else ''))
    if not cond:
        FAILS.append(name)


def main():
    for p in (NEW, OLD):
        if not os.path.exists(p):
            print('缺文件：%s' % p)
            return 1
    print('新版 %s' % os.path.basename(NEW))
    print('旧版 %s（板上那版）' % os.path.basename(OLD))

    os.environ['GLC_SIZE'] = '256'
    os.environ.pop('GLC_ALLOW_512', None)
    new = load(NEW, 'daemon_new')
    old = load(OLD, 'daemon_old')

    tmp = tempfile.mkdtemp(prefix='glcprep_')
    try:
        # 造一张 640×480 的合成图（与相机同尺寸）
        w, h = 640, 480
        yy, xx = np.mgrid[0:h, 0:w]
        rgb = np.stack([xx * 255 // (w - 1), yy * 255 // (h - 1),
                        ((xx * 3 + yy * 5) % 256)], axis=2).astype(np.uint8)
        jpg = os.path.join(tmp, 'in.jpg')
        Image.fromarray(rgb).save(jpg, quality=92)

        for mode in ('fit', 'crop', 'squash'):
            a, pa = new.prepare(jpg, mode)
            b, pb = old.prepare(jpg, mode)
            same = a.shape == b.shape and np.array_equal(a, b)
            check('T-%s 新旧张量逐元素相同' % mode, same,
                  'shape %s vs %s  max|diff|=%.3g'
                  % (a.shape, b.shape, float(np.abs(a - b).max()) if a.shape == b.shape else -1))
            if pa is not None and pb is not None:
                check('T-%s 预览图也相同' % mode, np.array_equal(np.asarray(pa), np.asarray(pb)))

        # raw 模式（256 字节数 = 196608）
        im = Image.open(jpg).convert('RGB')
        px = im.crop(((w - 256) // 2, (h - 256) // 2,
                      (w - 256) // 2 + 256, (h - 256) // 2 + 256))
        raw = os.path.join(tmp, 'f.raw')
        open(raw, 'wb').write(px.tobytes())
        a, _ = new.prepare(raw, 'raw256')
        try:
            b, _ = old.prepare(raw, 'raw256')
        except Exception as e:
            # 旧版（4f51fd3d = git 65e1d86）**还没有 raw256 模式**，无从比较
            print('  ⏭  T-raw256 跳过：旧版没有这个模式（%s）' % type(e).__name__)
            b = None
        if b is not None:
            check('T-raw256 新旧张量逐元素相同', np.array_equal(a, b),
                  'max|diff|=%.3g' % float(np.abs(a - b).max()))

        check('T5 形状 = (1,256,256,3)', a.shape == (1, 256, 256, 3), str(a.shape))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('\n' + '=' * 62)
    if FAILS:
        print('失败 %d 条：%s' % (len(FAILS), ' / '.join(FAILS)))
        return 1
    print('全部通过 ✅  prepare() 在 256 下与板上那版逐字节等价（fit / crop / squash + 预览图）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
