# -*- coding: utf-8 -*-
r"""Probe @scales entries in a *_ZG.json: per-tensor or per-channel?

Usage: python qscale_probe.py <ZG.json> [more.json ...]

A scale string looks like  @scales([axis=K]<body>)
  body = "N*value"                -> one value broadcast over N elements (per-tensor)
  body = "v0,v1,v2,..."           -> one value per element along axis K (per-channel)
  body = ""                       -> no scale (e.g. weight stored per-channel elsewhere)
"""
import json
import re
import sys

PAIR = re.compile(r"^(\d+)\*([-+0-9.eE]+)$")


def walk(o, path, out):
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(v, str) and "@scales" in v:
                out.append((path + "/" + k, v))
            else:
                walk(v, path + "/" + k, out)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            walk(v, path + "/%d" % i, out)


def parse(v):
    """-> (axis, n_elem, ndistinct, vmin, vmax, kind)"""
    m = re.match(r"^@scales\(\[axis=(-?\d+)\](.*)\)\s*$", v)
    if not m:
        return (None, 0, 0, 0.0, 0.0, "other")
    ax, body = m.group(1), m.group(2)
    if body == "":
        return (ax, 0, 0, 0.0, 0.0, "empty")
    body = body.rstrip(",")
    mm = PAIR.match(body)
    if mm:
        return (ax, int(mm.group(1)), 1, float(mm.group(2)), float(mm.group(2)), "tensor")
    parts = [p for p in body.split(",") if p]
    try:
        vals = [float(p) for p in parts]
    except ValueError:
        return (ax, len(parts), -1, 0.0, 0.0, "other")
    return (ax, len(vals), len(set(vals)), min(vals), max(vals), "channel")


def main():
    top = int(sys.argv[1]) if sys.argv[1].isdigit() else 10
    files = sys.argv[2:] if sys.argv[1].isdigit() else sys.argv[1:]
    for fn in files:
        j = json.load(open(fn, encoding="utf-8"))
        out = []
        walk(j, "", out)
        kinds = {}
        rows = []
        for p, v in out:
            r = parse(v)
            kinds[r[5]] = kinds.get(r[5], 0) + 1
            rows.append((p, v, r))
        print("=" * 96)
        print("%s\n  name=%s  entries=%d  %s" % (fn, j.get("name"), len(out), kinds))
        # split params (weights) vs activations
        for cat, pred in (("params(weights)", lambda p: "/params/" in p),
                          ("activations   ", lambda p: "/params/" not in p)):
            sub = [r for r in rows if pred(r[0])]
            kk = {}
            for r in sub:
                kk[r[2][5]] = kk.get(r[2][5], 0) + 1
            sp = [r[2][4] / r[2][3] for r in sub if r[2][5] == "channel" and r[2][3] > 0]
            extra = ""
            if sp:
                sp.sort()
                extra = "  spread(max/min) med=%.2f max=%.2f" % (sp[len(sp) // 2], sp[-1])
            print("  %s n=%-5d %s%s" % (cat, len(sub), kk, extra))
        pc = [r for r in rows if r[2][5] == "channel"]
        if pc:
            nd = [r[2][2] for r in pc]
            print("  per-channel entries: %d ; distinct-count min/med/max = %d/%d/%d"
                  % (len(pc), min(nd), sorted(nd)[len(nd) // 2], max(nd)))
            # dynamic spread within one per-channel tensor = max/min of the scales
            sp = [r[2][4] / r[2][3] for r in pc if r[2][3] > 0]
            sp.sort()
            print("  within-tensor scale spread (max/min): med=%.2f  p90=%.2f  max=%.2f"
                  % (sp[len(sp) // 2], sp[int(len(sp) * 0.9)], sp[-1]))
            for p, v, r in pc[:2]:
                print("    e.g. %s\n         %s" % (p, v[:150]))
        pt = [r for r in rows if r[2][5] == "tensor"]
        pt.sort(key=lambda r: -r[2][4])
        print("  top %d per-tensor scales by value (larger = finer step if step=1/scale):" % top)
        for p, v, r in pt[:top]:
            ax, n, dv, mn, mx, k = r
            print("    n=%-8d scale=%-14.6g 1/scale=%-12.6g  %s" % (n, mx, 1.0 / mx if mx else 0, p[6:80]))


if __name__ == "__main__":
    main()
