#!/bin/bash
echo "===== psnr_check.py ====="
cat /root/glcdec/psnr_check.py
echo
echo "===== channel-order / alignment probe ====="
python3 - <<'PY'
import numpy as np, math

def psnr(a, b):
    mse = float(np.mean((a.astype('f8') - b.astype('f8')) ** 2))
    rng = float(max(a.max(), b.max()) - min(a.min(), b.min()))
    return 10 * math.log10(rng * rng / mse) if mse > 0 else 999.0

z = np.load('/root/dec_out/bf16c_p1.npz')
x = z['x_hat']                       # 板端 x_hat
ref = np.fromfile('/root/glc/inputs_photo/p1.ftmp', dtype='<f4')
print('x_hat', x.shape, 'ref flat', ref.shape)
print('x_hat range %.4f..%.4f  ref range %.4f..%.4f' % (x.min(), x.max(), ref.min(), ref.max()))

# try the layouts decode_board uses
cands = {}
xh = x[0]                                       # (3,H,W)
cands['CHW (as decode_board writes PNG)'] = xh.transpose(1, 2, 0)   # HWC
for name, arr in list(cands.items()):
    a = arr.reshape(-1)
    if a.size == ref.size:
        print('  %-38s PSNR=%.2f dB' % (name, psnr(a, ref)))
        b = arr[:, :, ::-1].reshape(-1)          # swap R and B
        print('  %-38s PSNR=%.2f dB   <-- R/B swapped' % (name + ' [BGR]', psnr(b, ref)))

# what does the reference look like? HWC or CHW?
r3 = ref.reshape(1, 3, 256, 256)
r_hwc = ref.reshape(256, 256, 3)
print()
print('ref as CHW: channel means', [round(float(r3[0, c].mean()), 4) for c in range(3)])
print('ref as HWC: channel means', [round(float(r_hwc[:, :, c].mean()), 4) for c in range(3)])
print('x_hat CHW : channel means', [round(float(xh[c].mean()), 4) for c in range(3)])
print('x_hat HWC : channel means', [round(float(xh.transpose(1,2,0)[:, :, c].mean()), 4) for c in range(3)])

# also try a few pixel shifts in case of misalignment
best = []
xh_hwc = xh.transpose(1, 2, 0)
for dy in (-1, 0, 1):
    for dx in (-1, 0, 1):
        for swap in (False, True):
            a = np.roll(np.roll(xh_hwc, dy, 0), dx, 1)
            if swap:
                a = a[:, :, ::-1]
            best.append((psnr(a.reshape(-1), ref), dy, dx, swap))
best.sort(reverse=True)
print()
print('top 5 over shifts/swap:')
for p, dy, dx, sw in best[:5]:
    print('   PSNR=%.2f  dy=%d dx=%d swapRB=%s' % (p, dy, dx, sw))
PY
echo ORDER_PROBE_DONE
