r"""打印 Icraft 解析后网络的算子序列与 compile_target（NPU/CPU 归属）"""
import json
import sys

for name in sys.argv[1:]:
    p = rf"E:\fudanwei\工作区\onnx\t3\run\jr_{name}\{name}_parsed.json"
    net = json.load(open(p, encoding="utf-8"))
    print(f"===== {name} =====")
    print(f"  ai_target={net['ai_target']}  framework={net['framework_kind']}/{net['framework_version']}  "
          f"icraft={net['icraft_version']}  xir={net.get('icraft_xir_version')}")
    hosts, zgs, others = [], [], []
    for o in net["ops"]:
        t = o["_type_key"].split("::")[-1]
        ct = o.get("compile_target", "?").replace("@", "")
        extra = ""
        if "eps" in o:
            extra = (f"   eps={o['eps']}  gamma={'有' if o.get('gamma') is not None else '无'}"
                     f"  beta={'有' if o.get('beta') is not None else '无'}")
        print(f"  [{o['op_id']:2d}] {t:24s} -> {ct}{extra}")
        if ct.startswith("host"):
            hosts.append(t)
        elif ct.startswith("zhuget") or ct.startswith("zg"):
            zgs.append(t)
        else:
            others.append(t)
    print(f"  → HostTarget(CPU): {len(hosts)} 个 {hosts if len(hosts) <= 8 else ''}")
    print(f"  → ZGTarget(NPU) : {len(zgs)} 个 {zgs if len(zgs) <= 8 else ''}")
    if others:
        print(f"  → 其他目标: {others}")
    print()
