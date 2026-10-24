# -*- coding: utf-8 -*-
r"""Diff the dequant scales of two *_ZG.json models built from the same graph.

Usage: python scale_diff.py A_ZG.json B_ZG.json

Both files are keyed by "<ops index>/<inputs|outputs>/<k>"; the ops index is
assumed to line up (same parsed+optimized graph).  For every key present in
both, we print how much the scale moved.  Big movement => calibration set /
calibration size really changed the quantisation; near-zero movement => the
calibration set is NOT the lever.
"""
import json
import re
import sys

PAT = re.compile(r"@scales\(\[axis=(-?\d+)\](.*)\)\s*$")


def collect(fn):
    j = json.load(open(fn, encoding="utf-8"))
    d = {}

    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, str) and "@scales" in v:
                    m = PAT.match(v)
                    if m and m.group(2):
                        body = m.group(2).rstrip(",")
                        mm = re.match(r"^(\d+)\*([-+0-9.eE]+)$", body)
                        kind = "tensor" if mm else "channel"
                        d[path] = (kind, float(mm.group(2)) if mm else None, v)
                else:
                    walk(v, path + "/" + k)
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, path + "/%d" % i)

    walk(j, "")
    return j, d


def main():
    ja, da = collect(sys.argv[1])
    jb, db = collect(sys.argv[2])
    ka, kb = set(da), set(db)
    both = ka & kb
    print("A=%s\nB=%s" % (sys.argv[1], sys.argv[2]))
    print("entries A=%d  B=%d  common=%d  A-only=%d  B-only=%d"
          % (len(ka), len(kb), len(both), len(ka - kb), len(kb - ka)))
    rows = []
    for k in both:
        (ta, va, _), (tb, vb, _) = da[k], db[k]
        if ta == "tensor" and tb == "tensor" and va and vb:
            rows.append((abs(vb - va) / va, va, vb, k))
    rows.sort(reverse=True)
    same = sum(1 for r in rows if r[0] == 0.0)
    print("per-tensor pairs compared = %d ; byte-identical scales = %d (%.1f%%)"
          % (len(rows), same, 100.0 * same / max(1, len(rows))))
    if rows:
        rel = sorted(r[0] for r in rows)
        print("relative change  med=%.4f  p90=%.4f  p99=%.4f  max=%.4f"
              % (rel[len(rel) // 2], rel[int(len(rel) * .9)],
                 rel[int(len(rel) * .99)], rel[-1]))
        print("--- 10 biggest movers ---")
        for r, va, vb, k in rows[:10]:
            print("  %+.1f%%  %.6g -> %.6g   %s" % (100 * r, va, vb, k[6:90]))


if __name__ == "__main__":
    main()
