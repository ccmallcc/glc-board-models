"""Reuse the proven recovery guard, testing the exact A/011 BF16 vector."""
import importlib.util, json, os, sys, time
from pathlib import Path
sys.dont_write_bytecode = True
TASK = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('red_guard', '/root/codexwork/20261027_red_recovery/board_check.py')
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)
G.TASK = TASK
G.__file__ = __file__

def worker(out):
    import numpy as np
    from PIL import Image
    import decode_batch as batch
    import rans_pl
    from glc_lock import hwlock
    def pixels(path):
        with Image.open(str(path)) as im:
            return np.asarray(im.convert('RGB')).copy()
    def compare(a, b):
        a, b = pixels(a).astype(np.float64), pixels(b).astype(np.float64)
        diff = a-b
        mse = float(np.mean(diff*diff))
        return dict(mae=float(np.mean(np.abs(diff))), max_difference=float(np.max(np.abs(diff))),
                    psnr=99.0 if mse == 0 else float(10*np.log10(255**2/mse)), mean_rgb=a.mean(axis=(0,1)).tolist())
    report = dict(passed=False, rows=[], scope='Isolated existing B PL/NPU decode of SSH-supplied A PC-produced BF16 vector; not wireless acceptance')
    engine = None
    try:
        assert os.environ.get('GLC_AD_BACKEND') == 'pl'
        eng = batch.load_engine()
        assert eng['ok'], eng['err']
        engine = eng['eng']
        with hwlock('bf16-codec-check-prepare', timeout=20) as lock:
            assert lock.held
            for key in batch.DEFER_KEYS:
                engine.load(key)
                engine.prepare_sessions([key])
            batch._warmup(eng, str(out))
        def decode(tag, source, calls):
            target = out/(tag+'.png')
            before = rans_pl.report()
            started = time.monotonic()
            if source.suffix == '.glc512':
                batch.large_image.decode_composite(source, target,
                    lambda s,t: batch._decode_tile_locked(eng,s,t,return_rgb=True), in_memory=True)
            else:
                batch._decode_tile_locked(eng,str(source),str(target))
            seconds = time.monotonic()-started
            stats = rans_pl.report()
            row = dict(tag=tag, input_md5=G.D.digest(source), png_md5=G.D.digest(target), seconds=seconds,
                pl_calls=stats['calls']-before['calls'], symbols=stats['symbols']-before['symbols'])
            assert row['pl_calls'] == calls
            if tag in ('legacy','bf16'):
                row['vs_original'] = compare(target,TASK/'original.jpg')
                row['vs_sender_reference'] = compare(target,TASK/'sender_reference.png')
            report['rows'].append(row)
            G.save(out/'worker_result.json', report)
            print('BF16_VECTOR '+json.dumps(row),flush=True)
            return target,row
        normal_before,_ = decode('normal_before',G.PACKET/'normal.glc',4)
        legacy,bad = decode('legacy',TASK/'legacy.glc',4)
        candidate,good = decode('bf16',TASK/'bf16.glc',4)
        large,_ = decode('large',G.PACKET/'s104.glc512',16)
        normal_after,_ = decode('normal_after',G.PACKET/'normal.glc',4)
        assert legacy.read_bytes() == (G.RX/'s182_rx1.png').read_bytes()
        assert np.array_equal(pixels(normal_before),pixels(G.PACKET/'normal_reference.png'))
        assert np.array_equal(pixels(normal_before),pixels(normal_after))
        assert np.array_equal(pixels(large),pixels(G.PACKET/'s104_reference.png'))
        assert good['vs_original']['psnr'] >= 20
        assert good['vs_original']['psnr'] >= bad['vs_original']['psnr']+10
        assert good['vs_sender_reference']['mae'] <= 8
        report.update(passed=True,ordinary_256_exact=True,large_512_exact=True,legacy_exact_same_red=True,
            bf16_A_PC_vector_validated_on_B=True,wireless_bf16_verified=False,legacy_292B_repaired=False)
    finally:
        if engine is not None:
            engine.close()
        G.save(out/'worker_result.json', report)
    print(json.dumps(report),flush=True)

G.worker = worker
if __name__ == '__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--worker':
        worker(Path(sys.argv[2]))
    else:
        G.guard()
