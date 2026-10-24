r"""对比 parse 与 quantize 后各算子的 compile_target，判断最终落在 NPU 还是 CPU"""
import json
import sys
from collections import Counter


def load(path):
    net = json.load(open(path, encoding="utf-8"))
    seq = []
    for o in net["ops"]:
        seq.append((o["op_id"], o["_type_key"].split("::")[-1],
                    o.get("compile_target", "?").replace("@", "")))
    return net, seq


def main(parsed, quantized, title):
    net1, s1 = load(parsed)
    net2, s2 = load(quantized)
    print(f"===== {title} =====")
    print(f"  parse    : {len(s1)} 节点, ai_target={net1['ai_target']}")
    print(f"  quantize : {len(s2)} 节点, ai_target={net2['ai_target']}")
    print()
    print(f"  {'parse 算子':<22} {'parse':<12} {'quantize 算子':<22} {'quantize':<12}")
    n = max(len(s1), len(s2))
    for i in range(n):
        a = s1[i] if i < len(s1) else (None, "-", "-")
        b = s2[i] if i < len(s2) else (None, "-", "-")
        mark = "  <<<" if (a[2] != b[2]) else ""
        print(f"  {a[1]:<22} {a[2]:<12} {b[1]:<22} {b[2]:<12}{mark}")

    print()
    c = Counter(x[2] for x in s2)
    print(f"  quantize 后目标分布: {dict(c)}")
    gg = [x for x in s2 if "Norm" in x[1]]
    for _, t, ct in gg:
        print(f"  ★ {t} → {ct}  ({'NPU ✅' if ct.startswith('zhuget') or ct.startswith('zg') else 'CPU（HostTarget）⚠️'})")
    print()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
