#!/bin/bash
echo "===== where does the container q_index come from ====="
grep -n "struct.pack\|HEADER\|'GLC2'\|GLC2\|>4sBBH17I" /root/glc/pack_full.sh /root/glc/pack_full0.sh 2>/dev/null | head -20
grep -rn "q_index\|qidx" /root/glc/*.py /root/glc/*.sh 2>/dev/null | head -10
python3 - <<'PY'
import struct
b = open('/root/photos_glc/p1.glc', 'rb').read()
f = struct.Struct('>4sBBH17I').unpack_from(b, 0)
print('header magic=%r ver=%d q_index=%d flag3=%d flag20=%d' % (f[0], f[1], f[2], f[3], f[20]))
print('dims =', f[4:15])
print('lens =', f[15:20], ' sum+76 =', 76 + sum(f[15:20]), ' file =', len(b))
PY

echo
echo "===== ★ is inputs_photo/pN.ftmp really the encoder input? ====="
python3 - <<'PY'
import numpy as np
from PIL import Image
for i in (1, 2, 3):
    ref = np.fromfile('/root/glc/inputs_photo/p%d.ftmp' % i, dtype='<f4').reshape(256, 256, 3)
    im = Image.open('/root/photos_glc/p%d.png' % i).convert('RGB')
    a = np.asarray(im, dtype=np.float32) / np.float32(127.5) - np.float32(1.0)
    d = np.abs(ref - a)
    mse = float((d.astype('f8') ** 2).mean())
    import math
    p = 10 * math.log10(4.0 / mse) if mse > 0 else 999.0
    print('  p%d: ref vs png  PSNR=%.2f dB  maxabs=%.6f  identical=%s'
          % (i, p, float(d.max()), bool(np.array_equal(ref, a))))
PY
echo
echo "===== does the encoder input tensor still sit in run/s1 ? ====="
ls -l /root/glc/run/s1/in0.ftmp 2>/dev/null
md5sum /root/glc/run/s1/in0.ftmp /root/glc/inputs_photo/p1.ftmp 2>/dev/null
echo REFCHECK_DONE
