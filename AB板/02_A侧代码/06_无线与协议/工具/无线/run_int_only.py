#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只跑集成层 4 个测试，把子进程输出完整打出来（诊断用）"""
import os
import random
import sys

sys.path.insert(0, '/root')
import test_session_proto as T          # noqa: E402

random.seed(20261009)
for name in ('t_int_normal', 't_int_nolens', 't_int_abort', 't_int_n63_retry'):
    f = getattr(T, name)
    print('#' * 70)
    try:
        ok = f()
        print('>>> %s = %s' % (name, ok))
    except Exception as e:
        print('>>> %s 异常: %s' % (name, e))
    sys.stdout.flush()
print('INT_ONLY_DONE')
