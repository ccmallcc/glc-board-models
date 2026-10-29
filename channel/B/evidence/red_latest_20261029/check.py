"""Offline, read-only verification of the red/BF16 evidence bundle."""
import hashlib, json
from pathlib import Path
import numpy as np
from PIL import Image
ROOT = Path(__file__).resolve().parent
report = json.loads((ROOT/'result.json').read_text(encoding='utf-8'))
for row in report['files']:
    data = (ROOT/row['name']).read_bytes()
    assert len(data)==row['bytes'] and hashlib.md5(data).hexdigest()==row['md5']
    assert hashlib.sha256(data).hexdigest()==row['sha256']
def pixels(name):
    with Image.open(ROOT/name) as im:
        assert im.size == (256,256)
        return np.asarray(im.convert('RGB'),dtype=np.float64)
def metrics(a,b):
    diff=pixels(a)-pixels(b)
    mse=float(np.mean(diff*diff))
    return dict(mae=float(np.mean(np.abs(diff))), psnr=99.0 if mse==0 else float(10*np.log10(255**2/mse)),max_difference=float(np.max(np.abs(diff))))
red=metrics('s182_rx1.png','original.jpg')
good=metrics('bf16_B_PL_NPU.png','original.jpg')
cross=metrics('bf16_B_PL_NPU.png','bf16_A_reference.png')
assert abs(red['psnr']-report['legacy_metrics']['psnr']) < 1e-9
assert abs(good['psnr']-report['bf16_metrics']['psnr']) < 1e-9
assert abs(cross['mae']-report['bf16_vs_A']['mae']) < 1e-9
assert good['psnr']>=20 and good['psnr']-red['psnr']>10
assert report['ordinary_256_exact'] and report['large_512_exact']
assert not report['wireless_bf16_verified'] and not report['legacy_292B_repaired']
print(json.dumps(dict(passed=True,files=len(report['files']),red_source_psnr=red['psnr'],bf16_source_psnr=good['psnr'],bf16_vs_A_mae=cross['mae'],scope='File hashes and pixels rechecked locally; historical hardware timings/PL call counts are recorded measurements, not rerun by this checker')))
