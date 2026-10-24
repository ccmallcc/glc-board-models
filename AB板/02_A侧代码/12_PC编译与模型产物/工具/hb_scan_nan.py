r"""扫描 icraft dump 的特征图，定位 NaN/Inf 首次出现的 v_id"""
import glob
import os
import sys

import numpy as np

dump = sys.argv[1]
files = glob.glob(os.path.join(dump, "*.ftmp"))
recs = []
for f in files:
    vid = int(os.path.basename(f)[:-5])
    a = np.fromfile(f, dtype=np.float32)
    if a.size == 0:
        continue
    n_nan = int(np.isnan(a).sum())
    n_inf = int(np.isinf(a).sum())
    finite = a[np.isfinite(a)]
    recs.append((vid, a.size, n_nan, n_inf,
                 float(finite.min()) if finite.size else float("nan"),
                 float(finite.max()) if finite.size else float("nan"),
                 float(np.abs(finite).max()) if finite.size else float("nan")))

recs.sort()
print(f"共 {len(recs)} 个特征图\n")
print(f"{'v_id':>6} {'元素数':>10} {'NaN':>8} {'Inf':>6} {'min':>12} {'max':>12}")
bad = [r for r in recs if r[2] or r[3]]
for r in recs[:24]:
    flag = "  <<< NaN/Inf" if (r[2] or r[3]) else ""
    print(f"{r[0]:>6} {r[1]:>10} {r[2]:>8} {r[3]:>6} {r[4]:>12.4f} {r[5]:>12.4f}{flag}")
print("  ...")
print(f"\n含 NaN/Inf 的特征图共 {len(bad)} 个，最早的是 v_id = "
      f"{bad[0][0] if bad else '无'}")
if bad:
    print("最早 10 个：", [b[0] for b in bad[:10]])
