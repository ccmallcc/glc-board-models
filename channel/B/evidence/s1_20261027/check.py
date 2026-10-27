"""Recompute the raw same-stage S1 comparisons from published arrays."""
import hashlib,json
from pathlib import Path
import numpy as np
d=Path(__file__).resolve().parent
r=json.loads((d/'report.json').read_text(encoding='utf-8'))
for row in r['samples']:
    name=row['name']
    for key in ('y','z'):
        ref=np.fromfile(d/(name+'_fp32_'+key+'.f32'),dtype=np.float32).astype(np.float64)
        for backend in ('npu','host','bf16_host'):
            p=d/(name+'_'+backend+'_'+key+'.f32')
            a=np.fromfile(p,dtype=np.float32).astype(np.float64)
            m=row[backend][key]
            assert hashlib.md5(p.read_bytes()).hexdigest()==m['md5']
            assert len(a)==len(ref) and np.isfinite(a).all()
            cosine=float(np.dot(a,ref)/(np.linalg.norm(a)*np.linalg.norm(ref)))
            rel=float(np.linalg.norm(a-ref)/np.linalg.norm(ref))
            assert abs(cosine-m['vs_fp32']['cosine'])<1e-10
            assert abs(rel-m['vs_fp32']['relative_l2'])<1e-10
        assert (d/(name+'_npu_'+key+'.f32')).read_bytes()==(d/(name+'_host_'+key+'.f32')).read_bytes()
print(json.dumps({'passed':True,'same_stage':True,'host_equals_B_NPU':True,'samples':len(r['samples'])}))
