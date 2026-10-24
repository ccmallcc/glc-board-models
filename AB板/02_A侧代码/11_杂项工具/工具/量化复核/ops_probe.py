# -*- coding: utf-8 -*-
r"""List the HardOps of a *_ZG.json: index, kind, output v_id, shape, bytes.

Usage: python ops_probe.py <ZG.json> [--csv out.csv] [--top N]

Prints a summary (op count, total dump bytes) and, with --csv, writes one line
per op so two models can be paired by op index.
"""
import json
import re
import sys


def np_of(shape):
    n = 1
    for s in shape:
        n *= s
    return n


def ed_of(v):
    """element_dtype can be a plain string like '@fp(32)' or a QuantizedType dict."""
    try:
        ed = v["dtype"]["element_dtype"]
    except Exception:
        return {}
    return ed if isinstance(ed, dict) else {"storage_dtype": ed}


def scale_of(v):
    ed = ed_of(v)
    s = ed.get("scale", "")
    if not isinstance(s, str):
        return "", ""
    m = re.match(r"^@scales\(\[axis=(-?\d+)\](.*)\)\s*$", s)
    if not m:
        return "", ""
    body = m.group(2).rstrip(",")
    mm = re.match(r"^(\d+)\*([-+0-9.eE]+)$", body)
    if mm:
        return "T", mm.group(2)
    if body:
        return "C", str(len(body.split(",")))
    return "", ""


def main():
    fn = sys.argv[1]
    top = 25
    csvout = ""
    a = sys.argv[2:]
    for i, x in enumerate(a):
        if x == "--top":
            top = int(a[i + 1])
        if x == "--csv":
            csvout = a[i + 1]
    j = json.load(open(fn, encoding="utf-8"))
    ops = j["ops"]
    rows = []
    tot = 0
    for i, o in enumerate(ops):
        st = ""
        if o.get("outputs"):
            st = ed_of(o["outputs"][0]).get("storage_dtype", "")
        vids = [v["v_id"] for v in o.get("outputs", [])]
        shape = o["outputs"][0]["dtype"]["shape"] if o.get("outputs") else []
        sk, sv = scale_of(o["outputs"][0]) if o.get("outputs") else ("", "")
        n = np_of(shape)
        tot += n * 4
        rows.append((i, o.get("name", "").split("::")[-1], o.get("op_id", 0),
                     vids[0] if vids else -1, "x".join(str(s) for s in shape),
                     n, st, sk, sv, (o.get("origin_ops_id") or [-1])[0]))
    print("FILE %s  name=%s  ops=%d  sum(all outputs, fp32 bytes)=%.1f MB"
          % (fn, j.get("name"), len(ops), tot / 1048576.0))
    kinds = {}
    for r in rows:
        kinds[r[1]] = kinds.get(r[1], 0) + 1
    print("op kinds: %s" % sorted(kinds.items(), key=lambda kv: -kv[1])[:14])
    print("--- first %d ops ---" % top)
    print("%-5s %-26s %-8s %-18s %-10s %-4s %s"
          % ("idx", "kind", "v_id", "shape", "numel", "st", "scale"))
    for r in rows[:top]:
        print("%-5d %-26s %-8d %-18s %-10d %-4s %s %s" % (r[0], r[1], r[3], r[4], r[5], r[6], r[7], r[8]))
    if csvout:
        import csv as _csv
        with open(csvout, "w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(["idx", "kind", "op_id", "v_id", "shape", "numel", "storage", "skind", "scale", "origin"])
            w.writerows(rows)
        print("-> %s" % csvout)


if __name__ == "__main__":
    main()
