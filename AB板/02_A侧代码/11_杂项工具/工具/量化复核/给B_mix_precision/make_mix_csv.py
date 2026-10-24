# -*- coding: utf-8 -*-
r"""Build a mixed-precision CSV for Icraft from the auto-generated template.

Rationale (from the layer-wise study, reports\逐层量化误差分析报告.md):
INT8's error is concentrated in the *element-wise* ops (Add / Multiply), the
attention Matmul and InstanceNorm2d -- NOT in Conv2d.  So the cheapest way to
recover accuracy is to keep Conv2d (the bulk of the FLOPs) at INT8 and promote
everything element-wise to BF16.

The template emitted by icraft-quantize lists op_id / op_type already in the
*optimized* graph's numbering, which is exactly what --mix_precision expects.

Usage:
  python make_mix_csv.py --template <..._quantize_mix_config.csv> --out <csv>
                         [--base int8] [--promote bf16]
                         [--keep-int8 Conv2dNode,TransposeNode,ReshapeNode,...]
                         [--softmax-null]
"""
import argparse
import csv
import sys
from collections import Counter


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--base", default="int8")
    ap.add_argument("--promote", default="bf16")
    ap.add_argument("--keep-int8", default="Conv2dNode,ConvTranspose2dNode,"
                                           "TransposeNode,ReshapeNode,SplitNode,"
                                           "PadNode,SliceNode,ConcatNode")
    ap.add_argument("--softmax-null", action="store_true", default=True)
    ap.add_argument("--no-softmax-null", dest="softmax_null", action="store_false")
    ap.add_argument("--int8-per", default="tensor",
                    help="per for the ops kept at --base (tensor|channel)")
    a = ap.parse_args()

    keep = set(x.strip() for x in a.keep_int8.split(",") if x.strip())
    rows = list(csv.DictReader(open(a.template, encoding="utf-8")))
    if not rows:
        print("empty template")
        return 1
    cols = list(rows[0].keys())
    stat = Counter()

    for r in rows:
        typ = r["op_type"].split("::")[-1]
        if typ in ("InputNode", "OutputNode", "Input", "Output"):
            r["dtype"] = "fp32"
            stat["fp32(io)"] += 1
        elif typ in keep:
            r["dtype"] = a.base
            stat["%s(%s)" % (a.base, typ)] += 1
        else:
            r["dtype"] = a.promote
            stat["%s(%s)" % (a.promote, typ)] += 1

        # value_range_in_bits must not exceed the dtype's range
        if r["dtype"] in ("bf16", "fp16"):
            r["value_range_in_bits"] = "16;16"
        elif r["dtype"] == "tf32":
            r["value_range_in_bits"] = "32;32"
        elif r["dtype"] == "int8":
            r["value_range_in_bits"] = "8;8"
        elif r["dtype"] == "fp32":
            r["value_range_in_bits"] = "32;32"

        # per: Multiply does not support per-channel (official mul_const note)
        if typ == "MultiplyNode":
            r["per"] = "tensor;tensor"
        elif r["dtype"] == a.base and typ in keep:
            r["per"] = "%s;%s" % (a.int8_per, a.int8_per)

        # softmax: kld can saturate the large values and blow up the output
        if typ == "SoftmaxNode" and a.softmax_null:
            r["saturation"] = "null;null"

    with open(a.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    print("template ops: %d" % len(rows))
    for k, v in sorted(stat.items(), key=lambda kv: -kv[1]):
        print("  %-28s %d" % (k, v))
    dtypes = Counter(r["dtype"] for r in rows)
    print("dtype 分布: %s" % dict(dtypes))
    print("written %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
