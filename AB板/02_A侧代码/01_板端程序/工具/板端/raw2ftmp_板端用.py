import sys, numpy as np
raw = np.fromfile(sys.argv[1], dtype=np.uint8)
n = 256 * 256 * 3
if raw.size != n:
    print("ERR size", raw.size, "!=", n); sys.exit(2)
t = (raw.reshape(256, 256, 3).astype(np.float32) / np.float32(127.5) - np.float32(1.0))
t = t.reshape(1, 256, 256, 3).astype(np.float32)
t.tofile(sys.argv[2])
print("OK ftmp", sys.argv[2], t.shape, t.dtype)
