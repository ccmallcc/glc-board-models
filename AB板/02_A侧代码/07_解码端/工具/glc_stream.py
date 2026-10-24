# -*- coding: utf-8 -*-
r"""V12 + V13: the board -> PC transport, end to end.

V13 (protocol)
--------------
One GLC2 container per frame:

    offset  size  field
    0       4     magic   b"GLCS"
    4       1     version = 1
    5       1     flags   (bit0: last frame)
    6       4     seq     monotonically increasing, starts at 0
    10      4     length  payload bytes (the whole .glc container)
    14      4     crc32   of the payload (zlib.crc32)
    ---- 18 bytes ---- then `length` bytes of payload

WHY TCP AND NOT UDP
    The containers are not all small.  At 256x256 q0 they are ~313 B, but the
    team's own images (up to 1920x1080) produce containers of several KB --
    measured up to 6905 B in result2.  A UDP datagram's safe payload is 1472 B
    (1500 MTU - 20 IP - 8 UDP), so UDP would need application-level
    fragmentation and reassembly for the large frames, for no benefit: the
    bitrate is ~5 KB/s even at 30 fps, i.e. <0.01% of a gigabit link.  TCP with
    TCP_NODELAY gives correctness for free and its latency contribution at this
    size is far below one frame time.  So: TCP, no fragmentation, no reassembly.

V12 (PC side)
    `--recv`  : accept a connection, parse frames, optionally decode with the
                stock compressai path, and report per-frame latency + fps.
    `--send`  : replay a directory of .glc containers (the "board" side), used
                for the loopback test since we have no board yet.

Usage
    # loopback self-test (spawns a receiver, replays containers, checks CRC/seq)
    python glc_stream.py --selftest --dir <v3/golden> [--decode]

    # or run the two halves yourself
    python glc_stream.py --recv --port 9100 --out <dir> [--decode]
    python glc_stream.py --send --dir <v3/golden> --port 9100
"""
import argparse
import glob
import json
import os
import socket
import struct
import sys
import threading
import time
import zlib

MAGIC = b"GLCS"
VERSION = 1
HDR = struct.Struct(">4sBBIII")          # magic, version, flags, seq, length, crc32
FLAG_LAST = 0x01
MAX_PAYLOAD = 64 * 1024 * 1024           # sanity bound

# The Windows console defaults to GBK here, which cannot encode the status
# glyphs; do not let a print() kill a working transfer.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def pack_frame(payload: bytes, seq: int, last: bool = False) -> bytes:
    return HDR.pack(MAGIC, VERSION, FLAG_LAST if last else 0, seq,
                    len(payload), zlib.crc32(payload) & 0xFFFFFFFF) + payload


def recv_exactly(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


def read_frame(sock):
    """Returns (seq, payload, last) or None on clean EOF. Raises on corruption."""
    h = recv_exactly(sock, HDR.size)
    if h is None:
        return None
    magic, ver, flags, seq, length, crc = HDR.unpack(h)
    if magic != MAGIC:
        raise ValueError("bad magic %r" % magic)
    if ver != VERSION:
        raise ValueError("unsupported version %d" % ver)
    if length > MAX_PAYLOAD:
        raise ValueError("implausible length %d" % length)
    payload = recv_exactly(sock, length)
    if payload is None:
        raise ValueError("truncated payload (seq %d)" % seq)
    if (zlib.crc32(payload) & 0xFFFFFFFF) != crc:
        raise ValueError("CRC mismatch on seq %d" % seq)
    return seq, payload, bool(flags & FLAG_LAST)


# ---------------------------------------------------------------------------
def sender(port, files, host="127.0.0.1", fps=0.0, verbose=True):
    s = socket.create_connection((host, port), timeout=10)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    total = 0
    t0 = time.time()
    for i, f in enumerate(files):
        payload = open(f, "rb").read()
        s.sendall(pack_frame(payload, i, last=(i == len(files) - 1)))
        total += len(payload)
        if fps > 0:
            time.sleep(1.0 / fps)
    s.shutdown(socket.SHUT_WR)
    dt = time.time() - t0
    if verbose:
        print("  sent %d frames, %d B in %.3fs (%.1f KB/s)"
              % (len(files), total, dt, total / 1024.0 / max(1e-9, dt)))
    s.close()
    return len(files), total


def receiver(port, out_dir, decode=False, repo=None, model_path=None,
             device="cpu", host="127.0.0.1", results=None, verbose=True):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(1)
    if verbose:
        print("  listening on %s:%d" % (host, port))
    conn, addr = srv.accept()
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    model = em = None
    if decode:
        import types
        import torch
        repo = os.path.abspath(repo)
        sys.path.insert(0, repo)
        sys.path.insert(0, os.path.join(repo, "src", "utils"))
        stub = types.ModuleType("src.utils.metric_image")
        stub.evaluate_quality = lambda *x, **k: None
        sys.modules["src.utils.metric_image"] = stub
        import test_image_complement2 as T
        from src.models.image_model import GLC_Image
        from src.utils.test_utils import get_state_dict, init_func, write_image
        init_func()
        dev = torch.device(device)
        model = GLC_Image(inplace=True).to(dev)
        model.load_state_dict(get_state_dict(model_path), strict=True)
        model.eval()
        em = T.build_entropy_model(dev)
        _T, _write = T, write_image

    os.makedirs(out_dir, exist_ok=True)
    rows = []
    seq_expected = 0
    while True:
        t_recv0 = time.time()
        got = read_frame(conn)
        if got is None:
            break
        seq, payload, last = got
        t_recv1 = time.time()
        ok_seq = (seq == seq_expected)
        seq_expected = seq + 1
        rec = {"seq": seq, "bytes": len(payload), "seq_ok": ok_seq,
               "recv_ms": (t_recv1 - t_recv0) * 1000.0}
        gp = os.path.join(out_dir, "frame_%04d.glc" % seq)
        open(gp, "wb").write(payload)
        if decode:
            import torch
            t_d0 = time.time()
            with torch.no_grad():
                x_hat, _ = _T.decompress_glc(model, em, payload)
            t_d1 = time.time()
            _write(os.path.join(out_dir, "frame_%04d.png" % seq), x_hat)
            t_d2 = time.time()
            rec["dec_ms"] = (t_d1 - t_d0) * 1000.0        # entropy decode + network
            rec["png_ms"] = (t_d2 - t_d1) * 1000.0        # encode PNG to disk
        rows.append(rec)
        if verbose and (seq < 3 or last):
            print("  frame %4d  %6d B  seq_ok=%s%s" %
                  (seq, len(payload), ok_seq,
                   ("  dec=%.1f ms  png=%.1f ms" % (rec["dec_ms"], rec["png_ms"]))
                   if "dec_ms" in rec else ""))
        if last:
            break
    conn.close()
    srv.close()
    n = len(rows)
    summary = {
        "frames": n,
        "bytes": sum(r["bytes"] for r in rows),
        "seq_all_ok": all(r["seq_ok"] for r in rows),
        "recv_ms_mean": (sum(r["recv_ms"] for r in rows) / n) if n else None,
        "dec_ms_mean": (sum(r["dec_ms"] for r in rows if "dec_ms" in r) /
                        max(1, sum(1 for r in rows if "dec_ms" in r))) if decode else None,
        "dec_ms_excl_first": (sum(r["dec_ms"] for r in rows[1:] if "dec_ms" in r) /
                              max(1, sum(1 for r in rows[1:] if "dec_ms" in r))) if decode else None,
        "png_ms_mean": (sum(r["png_ms"] for r in rows if "png_ms" in r) /
                        max(1, sum(1 for r in rows if "png_ms" in r))) if decode else None,
    }
    if verbose:
        print("  received %d frames, %d B, seq_ok=%s" %
              (n, summary["bytes"], summary["seq_all_ok"]))
        if decode:
            print("  decode %.1f ms/frame (first frame %.1f ms = CUDA warmup); PNG %.1f ms"
                  % (summary["dec_ms_mean"], rows[0].get("dec_ms", 0),
                     summary["png_ms_mean"]))
    if results is not None:
        results.update(summary)
        results["rows"] = rows
    return summary


def selftest(a):
    files = sorted(glob.glob(os.path.join(a.dir, "*.glc")))
    if not files:
        print("no .glc under %s" % a.dir)
        return 2
    print("loopback: %d containers from %s" % (len(files), a.dir))
    res = {}
    th = threading.Thread(target=receiver,
                          args=(a.port, a.out, a.decode, a.repo, a.model_path,
                                a.device, "127.0.0.1", res, True))
    th.start()
    time.sleep(0.4)
    t0 = time.time()
    sender(a.port, files)
    th.join()
    dt = time.time() - t0
    print("\nframes=%s  bytes=%s  seq_all_ok=%s" %
          (res.get("frames"), res.get("bytes"), res.get("seq_all_ok")))
    if res.get("dec_ms_mean"):
        print("decode mean = %.1f ms/frame (excluding first/warmup: %.1f ms); PNG %.1f ms"
              % (res["dec_ms_mean"], res.get("dec_ms_excl_first") or 0,
                 res.get("png_ms_mean") or 0))
    print("wall clock  = %.3f s for %d frames (%.1f fps, incl. decode=%s)"
          % (dt, len(files), len(files) / max(1e-9, dt), a.decode))
    # every payload must be byte-identical to the file we sent
    bad = 0
    for i, f in enumerate(files):
        gp = os.path.join(a.out, "frame_%04d.glc" % i)
        if not os.path.exists(gp) or open(gp, "rb").read() != open(f, "rb").read():
            bad += 1
    print("payload integrity: %d/%d byte-identical" % (len(files) - bad, len(files)))
    ok = (res.get("frames") == len(files) and res.get("seq_all_ok") and bad == 0)
    json.dump(res, open(os.path.join(a.out, "stream_results.json"), "w"),
              ensure_ascii=False, indent=2)
    print("\n%s" % ("==== V12/V13 闭环: 通过 ✅ ====" if ok else "==== 失败 ❌ ===="))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--recv", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dir", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9100)
    ap.add_argument("--decode", action="store_true")
    ap.add_argument("--fps", type=float, default=0.0)
    ap.add_argument("--repo", default=r"E:\fudanwei\工作区\GLC-main\GLC-main")
    ap.add_argument("--model_path",
                    default=r"E:\fudanwei\工作区\GLC-main\GLC-main\pretrained\GLC_image.pth.tar")
    ap.add_argument("--device", default="cpu")
    a = ap.parse_args()

    if a.selftest:
        a.out = a.out or r"E:\fudanwei\工作区\v12\recv"
        return selftest(a)
    if a.send:
        files = sorted(glob.glob(os.path.join(a.dir, "*.glc")))
        return 0 if sender(a.port, files, a.host, a.fps) else 1
    if a.recv:
        r = receiver(a.port, a.out, a.decode, a.repo, a.model_path, a.device,
                     a.host, None, True)
        return 0 if r["seq_all_ok"] else 1
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
