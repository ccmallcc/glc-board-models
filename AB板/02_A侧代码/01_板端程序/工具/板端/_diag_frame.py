import numpy as np
P = '/dev/shm/gigecam.bin'
a = np.fromfile(P, dtype=np.uint8)
n = a.size
print('file bytes =', n)
img = a.reshape(256, 256, 3).astype(np.float32)
lum = img.mean(axis=2)
# 32x32 块均值 -> ASCII
b = lum.reshape(32, 8, 32, 8).mean(axis=(1, 3))
chars = ' .:-=+*#%@'
lo, hi = float(b.min()), float(b.max())
print('lum min=%.1f max=%.1f mean=%.1f' % (lo, hi, lum.mean()))
for r in range(32):
    line = ''
    for c in range(32):
        v = (b[r, c] - lo) / max(1e-6, hi - lo)
        line += chars[min(9, int(v * 9.99))]
    print(line)
# 前 12 个像素的原始三元组，看有没有 2 像素周期（马赛克特征）
print('row128 px0..11 RGB:')
row = img[128].astype(int)
print(' '.join('(%d,%d,%d)' % (p[0], p[1], p[2]) for p in row[:12]))
# 列均值的三通道走势（取前 16 列）
print('col mean R/G/B, first 16 cols:')
cm = img[:, :16, :].mean(axis=0)
for c in range(16):
    print(' c%02d R=%5.1f G=%5.1f B=%5.1f' % (c, cm[c, 0], cm[c, 1], cm[c, 2]))
