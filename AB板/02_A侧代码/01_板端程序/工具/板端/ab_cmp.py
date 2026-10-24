import sys
import numpy as np

paths = [('/dev/shm/gigecam.bin', 'shm'), ('/tmp/cmp/frame01_256x256_rgb8.raw', 'official')]
for p, tag in paths:
    try:
        a = np.fromfile(p, dtype=np.uint8)
        if a.size != 196608:
            print(tag, 'size', a.size, '(skip)')
            continue
        img = a.reshape(256, 256, 3).astype(np.float32)
        d = float(np.abs(np.diff(img, axis=1)).mean())
        even = img[:, 0::2, :].mean(axis=(0, 1))
        odd = img[:, 1::2, :].mean(axis=(0, 1))
        print('%-9s mean %s neighbor %.2f max %d'
              % (tag, np.round(img.mean(axis=(0, 1)), 1), d, int(img.max())))
        print('%-9s even %s odd %s' % ('', np.round(even, 1), np.round(odd, 1)))
    except Exception as e:
        print(tag, 'ERR', e)
