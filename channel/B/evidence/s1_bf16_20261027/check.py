"""Recheck B BF16 NPU output against the already published Host vectors."""
import hashlib,json
from pathlib import Path
import numpy as np
d=Path(__file__).resolve().parent
r=json.loads((d/'report.json').read_text(encoding='utf-8'))
for name in ('original','bright16'):
    row=next(x for x in r['rows'] if x['name']==name)
    for key in ('y','z'):
        p=d/(name+'_'+key+'.f32')
        h=d.parent/'s1_20261027'/(name+'_bf16_host_'+key+'.f32')
        ref=d.parent/'s1_20261027'/(name+'_fp32_'+key+'.f32')
        assert p.read_bytes()==h.read_bytes()
        assert hashlib.md5(p.read_bytes()).hexdigest()==row['outputs'][key]['md5']
        a=np.fromfile(p,dtype=np.float32).astype(np.float64)
        b=np.fromfile(ref,dtype=np.float32).astype(np.float64)
        rel=float(np.linalg.norm(a-b)/np.linalg.norm(b))
        assert abs(rel-row['outputs'][key]['vs_fp32']['relative_l2'])<1e-10
print(json.dumps({'passed':True,'bf16_NPU_equals_Host':True,'samples':2}))
