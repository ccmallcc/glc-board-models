#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""glc_board_full_rsd.py —— 用**常驻引擎**跑 glc_board_full，其余逻辑一行不改

做法：把 glc_board_full 当模块导入，只替换它的 `run_npu` 全局名。
      main() 里是 `run_npu(...)` 的模块级查找，所以替换模块属性即可生效。
      ⇒ 胶水层 / 打包 / PL rANS / 容器组装 **全部沿用原脚本**，便于对拍。

用法（与原来完全一样）：
    python3 /root/glc/glc_board_full_rsd.py --sample 0
"""
import sys
import time

sys.path.insert(0, "/root/glc")

import glc_board_full as G          # noqa: E402
import glc_rsd                      # noqa: E402

_engine = None
_t_boot = None


def _run_npu(key, cwd):
    global _engine, _t_boot
    if _engine is None:
        _t_boot = time.time()
        print("### GLC 常驻引擎：首次调用，开始载入 5 个子图（只付一次）###")
        sys.stdout.flush()
        _engine = glc_rsd.Engine(G.MODELS)
    return _engine.run(key, cwd)


# ★ 只改这一处
G.run_npu = _run_npu


def main():
    t_all = time.time()
    rc = None
    err = None
    try:
        rc = G.main()
    except SystemExit as e:
        rc = e.code
    except Exception as e:
        err = e
        import traceback
        traceback.print_exc()
    print("=" * 66)
    if _engine is not None:
        print(_engine.summary())
    print("### rc=%s  脚本墙钟 %.3f s" % (rc, time.time() - t_all))
    if _engine is not None:
        print("###   其中引擎一次性载入 %.3f s，其余 %.3f s 是编码+胶水+PL rANS+容器"
              % (_engine.t_setup, time.time() - t_all - _engine.t_setup))
    if err is not None:
        print("### 异常: %s" % err)
    print("RSD_DONE")


if __name__ == "__main__":
    main()
