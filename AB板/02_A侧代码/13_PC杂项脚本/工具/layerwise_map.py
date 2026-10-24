# -*- coding: utf-8 -*-
r"""Map layer-wise comparison v_ids back to the producing op (Icraft parsed json).

Usage:
  python layerwise_map.py --sub s1 --vids 62,127,1288,235,1153
"""
import argparse
import json
import os
import sys

JR = r"E:\fudanwei\工作区\onnx\c1_simple\run"
SUB = {"s1": "s1_encoder_ga_hyper", "s2": "s2_hyperdec_fusion",
       "s3p1": "s3_phase1", "s3p2": "s3_phase2", "s3p3": "s3_phase3",
       "s4": "s4_gs_generator"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sub", default="s1")
    ap.add_argument("--vids", required=True)
    ap.add_argument("--all", action="store_true",
                    help="print the whole op table instead of a v_id subset")
    a = ap.parse_args()

    name = SUB[a.sub]
    p = os.path.join(JR, "jr_" + name, name + "_parsed.json")
    net = json.load(open(p, encoding="utf-8"))
    m = {}
    for o in net["ops"]:
        for v in (o.get("outputs") or []):
            if isinstance(v, dict) and isinstance(v.get("v_id"), int):
                d = v.get("dtype") or {}
                m[v["v_id"]] = (o.get("op_id"),
                                o.get("_type_key", "").split("::")[-1],
                                d.get("shape"), str(o.get("compile_target")))
    print("=== %s (%d ops, %d output v_ids) ===" % (name, len(net["ops"]), len(m)))
    want = None if a.all else [int(x) for x in a.vids.split(",") if x.strip()]
    keys = sorted(m) if want is None else [v for v in want if v in m]
    for v in keys:
        op_id, typ, shp, tgt = m[v]
        print("  v_id %-6d op_id %-5s %-18s shape=%-24s target=%s"
              % (v, op_id, typ, shp, tgt))
    miss = [] if want is None else [v for v in want if v not in m]
    if miss:
        print("  (v_id not in parsed graph: %s)" % miss)
    return 0


if __name__ == "__main__":
    sys.exit(main())
