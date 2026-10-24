r"""分析 Icraft 解析产出的 json（网络结构），核对算子映射与是否有 Unsupport 占位"""
import json
import sys
from collections import Counter


def analyze(path):
    with open(path, encoding="utf-8") as fh:
        net = json.load(fh)

    nodes = None
    for key in ("ops", "operations", "nodes", "op_list"):
        if isinstance(net, dict) and key in net:
            nodes = net[key]
            break
    if nodes is None:
        # 退化为遍历所有 list-of-dict 的字段
        for k, v in net.items():
            if isinstance(v, list) and v and isinstance(v[0], dict) and ("type" in v[0] or "op_type" in v[0]):
                nodes = v
                print(f"[info] 节点列表字段: {k}")
                break

    print(f"=== {path.split(chr(92))[-1]} ===")
    if not isinstance(net, dict):
        print("  顶层不是 dict，类型:", type(net))
        return
    print(f"  顶层字段: {list(net.keys())[:12]}")

    if nodes is None:
        print("  未能自动定位节点列表；打印前 600 字符供人工核对：")
        print("  " + json.dumps(net, ensure_ascii=False)[:600])
        return

    types = Counter()
    for nd in nodes:
        t = nd.get("type") or nd.get("op_type") or "?"
        types[t] += 1
    print(f"  节点数: {len(nodes)}")
    print("  算子分布: " + ", ".join(f"{k}×{v}" if v > 1 else k for k, v in types.most_common()))

    bad = [t for t in types if "nsupport" in t or "nknown" in t]
    print("  Unsupport/Unknown 占位: " + (", ".join(bad) if bad else "**无** ✅"))

    # 打印与归一化相关的节点细节
    for nd in nodes:
        t = nd.get("type") or nd.get("op_type") or ""
        if "Norm" in t or "norm" in t:
            attrs = {k: v for k, v in nd.items() if k not in ("inputs", "outputs")}
            print(f"  · {t}: {json.dumps(attrs, ensure_ascii=False)[:300]}")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        analyze(p)
        print()
