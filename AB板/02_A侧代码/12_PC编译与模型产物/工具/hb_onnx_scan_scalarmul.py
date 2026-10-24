# -*- coding: utf-8 -*-
r"""Scan a GLC subgraph ONNX for Mul nodes with a 1-element constant operand.

The Icraft zhuge HostBackend emulation crashes on `Multiply(value, scalar)`
under INT8 ("Index 1 out of bounds 1" in zgi::VpeRoutInst::setXvlen_en), so we
need to know exactly how many such nodes exist, what feeds them and what the
scalar value is -- to decide whether broadcasting the scalar to a per-channel
tensor is a safe, numerically identical rewrite.

Usage:
  python hb_onnx_scan_scalarmul.py --onnx <path> [--max 40]
"""
import argparse
import sys
from collections import Counter

import numpy as np
import onnx
from onnx import numpy_helper


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx", required=True)
    ap.add_argument("--max", type=int, default=40)
    a = ap.parse_args()

    m = onnx.load(a.onnx, load_external_data=False)
    g = m.graph

    init = {t.name: numpy_helper.to_array(t) for t in g.initializer}
    print("graph=%s  nodes=%d  initializers=%d" % (g.name, len(g.node), len(init)))

    # value_info for shapes where available
    shapes = {}
    for vi in list(g.value_info) + list(g.input) + list(g.output):
        tt = vi.type.tensor_type
        if tt.HasField("shape"):
            shapes[vi.name] = [d.dim_value if d.HasField("dim_value") else -1
                               for d in tt.shape.dim]

    producer = {}
    for i, n in enumerate(g.node):
        for o in n.output:
            producer[o] = i

    def const_of(name):
        if name in init:
            return init[name]
        i = producer.get(name)
        if i is not None and g.node[i].op_type == "Constant":
            for at in g.node[i].attribute:
                if at.name == "value":
                    return numpy_helper.to_array(at.t)
        return None

    hits = []
    counts = Counter()
    for i, n in enumerate(g.node):
        counts[n.op_type] += 1
        if n.op_type != "Mul" or len(n.input) != 2:
            continue
        for which in (0, 1):
            c = const_of(n.input[which])
            if c is not None and c.size == 1:
                other = n.input[1 - which]
                hits.append((i, n.name, which, float(c.reshape(-1)[0]),
                             other, list(c.shape), shapes.get(other),
                             g.node[producer[other]].op_type if other in producer else "GRAPH_INPUT"))
                break

    print("\nMul nodes: %d   with 1-element const operand: %d" % (counts["Mul"], len(hits)))
    for (i, name, which, val, other, cshape, oshape, optype) in hits[:a.max]:
        print("  node[%d] name=%r  const_input_idx=%d  value=%.8g  const_shape=%s"
              % (i, name, which, val, cshape))
        print("        other operand %r shape=%s  produced_by=%s" % (other, oshape, optype))

    print("\n--- op_type histogram (top 25) ---")
    for k, v in counts.most_common(25):
        print("  %-20s %d" % (k, v))
    return 0


if __name__ == "__main__":
    sys.exit(main())
