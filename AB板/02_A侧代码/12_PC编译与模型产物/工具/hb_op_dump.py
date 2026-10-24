# -*- coding: utf-8 -*-
r"""Dump per-op key fields from an Icraft network json (parsed or quantized).

Usage:
  python hb_op_dump.py <json> [--ops 0-40] [--types InstanceNorm2d,Conv2d]
                       [--find-vid 32]

Prints op_id, type, compile_target, input/output element_dtype + v_id, and
selected numeric params so two networks (fp32 parsed vs quantized) can be
diffed side by side.
"""
import argparse
import json
import re
import sys

NUM_KEYS = (
    "eps", "epsilon", "alpha", "beta", "value_range_in_bits", "saturation",
    "per", "order", "qdtype", "mix_precision", "qparam", "scale", "zero_point",
    "fake_qf", "output_dtype", "input_dtype", "keep_dtype",
)


def short(t):
    """'@fp(32)' -> 'fp32', '@int(8)' -> 'int8'."""
    if not isinstance(t, str):
        return str(t)
    m = re.match(r"@(\w+)\((\d+)\)", t)
    if m:
        return m.group(1) + m.group(2)
    m = re.match(r"@(\w+)", t)
    return m.group(1) if m else t


def vinfo(v):
    if not isinstance(v, dict):
        return "?"
    dt = v.get("dtype", {})
    ed = short(dt.get("element_dtype")) if isinstance(dt, dict) else "?"
    shp = dt.get("shape") if isinstance(dt, dict) else None
    kind = "Params" if v.get("_type_key", "").endswith("Params") else "V"
    return "%s%s%s(id=%s)" % (kind, ed, ("x".join(str(x) for x in shp) if shp else ""),
                              v.get("v_id"))


def pick(op):
    """Collect interesting scalar params from an op dict."""
    out = {}
    for k, val in op.items():
        if k in NUM_KEYS:
            out[k] = val
        elif k in ("qparams", "quant_params") and isinstance(val, list):
            out[k] = val[:2]
    # nested per-output dtype info
    for i, o in enumerate(op.get("outputs") or []):
        if isinstance(o, dict) and "dtype" in o:
            out.setdefault("out_dtype", []).append(short(o["dtype"].get("element_dtype")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json_path")
    ap.add_argument("--ops", default="")
    ap.add_argument("--types", default="")
    ap.add_argument("--find-vid", type=int, default=-1)
    a = ap.parse_args()

    net = json.load(open(a.json_path, "r", encoding="utf-8"))
    ops = net["ops"]
    print("network=%s ai_target=%s ops=%d" % (net.get("name"), net.get("ai_target"), len(ops)))

    lo, hi = 0, len(ops) - 1
    if a.ops:
        m = re.match(r"(\d+)\s*-\s*(\d+)$", a.ops.strip())
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
        else:
            lo = hi = int(a.ops)

    want = set(t.strip() for t in a.types.split(",") if t.strip())

    for op in ops:
        oid = op.get("op_id", -1)
        typ = op.get("_type_key", "").split("::")[-1]
        ins = op.get("inputs") or []
        outs = op.get("outputs") or []
        vids = [v.get("v_id") for v in ins + outs if isinstance(v, dict)]

        hit = False
        if a.find_vid >= 0 and a.find_vid in vids:
            hit = True
        if want and typ in want:
            hit = True
        if not want and a.find_vid < 0 and lo <= oid <= hi:
            hit = True
        if not hit:
            continue

        print("\n[op %s] %s  target=%s  name=%r" % (oid, typ, op.get("compile_target"), op.get("name")))
        print("   in : " + ", ".join(vinfo(v) for v in ins))
        print("   out: " + ", ".join(vinfo(v) for v in outs))
        p = pick(op)
        if p:
            for k in sorted(p):
                print("   %-20s %s" % (k, json.dumps(p[k], ensure_ascii=False)[:300]))
        if want and a.find_vid < 0 and lo == 0 and hi == len(ops) - 1:
            continue


if __name__ == "__main__":
    sys.exit(main())
