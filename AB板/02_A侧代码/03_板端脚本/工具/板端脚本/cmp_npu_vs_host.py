import numpy as np, os
BOARD = r"E:\fudanwei\工作区\_board_run\logs_sfb\s1_encoder_ga_hyper\ftmpSFB"
HOST  = r"E:\fudanwei\工作区\_verify_npu\zg_int8\run_s1\dump\s1_encoder_ga_hyper\ftmpSFB"

def load(p, shp):
    return np.fromfile(p, dtype=np.float32).reshape(shp)

for vid, shp, name in ((3310, (1,16,16,256), "y"), (3314, (1,4,4,256), "z")):
    a = load(os.path.join(BOARD, "%d.ftmp" % vid), shp)   # 真 NPU
    b = load(os.path.join(HOST,  "%d.ftmp" % vid), shp)   # PC HostBackend
    d = (a - b).ravel()
    cos = float(a.ravel() @ b.ravel() / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-30))
    mse = float((d**2).mean())
    print("%s (v_id %d) shape=%s" % (name, vid, shp))
    print("   board(NPU)  min=%.4f max=%.4f mean=%.4f" % (a.min(), a.max(), a.mean()))
    print("   host(HB)    min=%.4f max=%.4f mean=%.4f" % (b.min(), b.max(), b.mean()))
    print("   cosine      = %.8f" % cos)
    print("   max|d|      = %.4e" % np.abs(d).max())
    print("   mean|d|     = %.4e" % np.abs(d).mean())
    print("   bit-equal   = %s" % bool(np.array_equal(a, b)))
    print()
