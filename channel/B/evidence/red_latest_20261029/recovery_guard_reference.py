"""Isolated current-PL/NPU comparison, with unconditional service recovery."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

TASK = Path(__file__).resolve().parent
PROD = Path('/root/tp5603_drv/glcdec')
RX = Path('/root/glc/pack/rxs')
PACKET = Path('/root/codexwork/20261025_pl_rans/board_package_v3')
sys.dont_write_bytecode = True
sys.path.insert(0, '/root/codexwork/20261024_large_image/src')
sys.path.insert(0, str(PROD))
import deploy_board as D

def obj(path):
    return json.loads(Path(path).read_text())

def save(path, value):
    D.atomic_write(path, json.dumps(value, indent=2).encode())

def worker(out):
    import numpy as np
    from PIL import Image
    import zlib
    import decode_batch as batch
    import rans_ad_np as ad
    import rans_pl
    from glc_lock import hwlock

    def pixels(path):
        return np.asarray(Image.open(str(path)).convert('RGB')).copy()

    def compare(left, right):
        a, b = pixels(left).astype(np.float64), pixels(right).astype(np.float64)
        mse = float(np.mean((a-b)**2))
        return dict(mae=float(np.mean(np.abs(a-b))), max_difference=float(np.max(np.abs(a-b))),
                    psnr=99.0 if mse == 0 else float(10*np.log10(255**2/mse)),
                    mean_rgb=a.mean(axis=(0,1)).tolist(),
                    mean_rgb_difference=np.abs(a.mean(axis=(0,1))-b.mean(axis=(0,1))).tolist())

    report = dict(passed=False, rows=[], method='Current installed PL rANS and NPU, private output directory')
    phases = []
    original_decode = ad.decode_symbols
    def capture(payload, indexes, cdf, cdf_len, offset):
        values = original_decode(payload, indexes, cdf, cdf_len, offset)
        idx = np.asarray(indexes, dtype=np.uint8).reshape(-1)
        phases.append(dict(crc32='%08X' % (zlib.crc32(idx.tobytes()) & 0xffffffff),
                           index_bytes=idx.tobytes(), symbols=len(values),
                           residual_min=int(np.min(values)), residual_max=int(np.max(values))))
        return values
    ad.decode_symbols = capture
    engine = None
    try:
        assert os.environ.get('GLC_AD_BACKEND') == 'pl'
        eng = batch.load_engine()
        assert eng['ok'], eng['err']
        engine = eng['eng']
        with hwlock('red-check-model-preparation', timeout=20) as lock:
            assert lock.held
            for key in batch.DEFER_KEYS:
                engine.load(key)
                engine.prepare_sessions([key])
            batch._warmup(eng, str(out))
        def decode(tag, source, calls):
            target = out/(tag+'.png')
            before = rans_pl.report()
            first = len(phases)
            started = time.monotonic()
            if source.suffix == '.glc512':
                batch.large_image.decode_composite(source, target,
                    lambda s,t: batch._decode_tile_locked(eng,s,t,return_rgb=True), in_memory=True)
            else:
                batch._decode_tile_locked(eng, str(source), str(target))
            stats = rans_pl.report()
            actual_calls = stats['calls']-before['calls']
            assert actual_calls == calls, (tag, actual_calls)
            selected = phases[first:]
            row = dict(tag=tag, input=str(source), output=str(target), seconds=time.monotonic()-started,
                       pl_calls=actual_calls, symbols=stats['symbols']-before['symbols'],
                       png_md5=D.digest(target), phases=[{k:v for k,v in x.items() if k!='index_bytes'} for x in selected],
                       combined_crc32='%08X' % (zlib.crc32(b''.join(x['index_bytes'] for x in selected)) & 0xffffffff))
            if tag in ('legacy', 'compatible'):
                row['vs_original'] = compare(target, TASK/'original.jpg')
                row['vs_sender_reference'] = compare(target, TASK/'sender_reference.png')
            report['rows'].append(row)
            save(out/'worker_result.json', report)
            print('RED_IMAGE '+json.dumps(row), flush=True)
            return target, row
        normal_before, _ = decode('normal_before', PACKET/'normal.glc', 4)
        legacy, legacy_row = decode('legacy', TASK/'legacy.glc', 4)
        compatible, good_row = decode('compatible', TASK/'compatible.glc', 4)
        big, _ = decode('large', PACKET/'s104.glc512', 16)
        normal_after, _ = decode('normal_after', PACKET/'normal.glc', 4)
        assert np.array_equal(pixels(normal_before), pixels(PACKET/'normal_reference.png'))
        assert np.array_equal(pixels(normal_before), pixels(normal_after))
        assert np.array_equal(pixels(big), pixels(PACKET/'s104_reference.png'))
        assert good_row['vs_original']['psnr'] >= 20
        assert good_row['vs_sender_reference']['mae'] <= 8
        assert max(good_row['vs_sender_reference']['mean_rgb_difference']) <= 15
        assert good_row['vs_original']['psnr'] >= legacy_row['vs_original']['psnr']+10
        inputs = obj(TASK/'inputs.json')
        actual_crc = [r['crc32'] for r in good_row['phases']]
        assert actual_crc == inputs['expected_peer_crc32'], actual_crc
        assert good_row['combined_crc32'] == inputs['expected_peer_combined_crc32']
        report.update(passed=True, ordinary_256_exact=True, large_512_exact=True,
            compatible_peer_crc_match=True, peer_crc_scope='Reported phase checksums; not a claim of collision-free proof',
            legacy_input_repaired=False, compatible_reencoding_validated=True,
            pl_report=rans_pl.report())
    finally:
        if engine is not None:
            engine.close()
        save(out/'worker_result.json', report)
    print(json.dumps(report), flush=True)

def guard():
    expected = obj(TASK/'expected.json')
    inputs = obj(TASK/'inputs.json')
    for row in inputs['files']:
        assert D.digest(TASK/row['name']) == row['md5']
    for name, row in expected['hashes'].items():
        assert D.digest(name) == row['md5'], 'Production identity changed: '+name
    state = obj(RX/'_status.json')
    assert not state.get('decoding') and state.get('pending', 0) == 0
    radio = D.clients('radio_rx_serve.py')
    out = TASK/('check_'+str(time.monotonic_ns()))
    out.mkdir()
    report = dict(passed=False, output=str(out), radio_before=[p for p,a in radio],
        before_fpga=Path('/sys/class/fpga_manager/fpga0/state').read_text().strip(),
        firmware=Path('/root/glc/loadbit').read_text().strip(),
        production_code_changed=False, original_gallery_modified=False)
    save(TASK/'current_check.json', report)
    stopped = False
    process = None
    try:
        stopped = True
        D.command('systemctl', 'stop', 'glc-demo')
        assert not D.clients('decode_batch.py') and not D.clients('glc_view.py')
        assert subprocess.run(['pgrep','-x','icraft-run'], stdout=subprocess.DEVNULL).returncode == 1
        env = dict(os.environ)
        env.update(expected['decoder_environment'])
        env.update(GLC_AD_BACKEND='pl', PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(out), TEMP=str(out), TMP=str(out))
        with (out/'worker.log').open('w') as log:
            process = subprocess.Popen([sys.executable, '-B', '-u', str(Path(__file__).resolve()), '--worker', str(out)],
                                       cwd=str(out), env=env, stdout=log, stderr=subprocess.STDOUT)
            report['worker_exit'] = process.wait(timeout=240)
        result = obj(out/'worker_result.json')
        assert report['worker_exit'] == 0 and result['passed'], 'Private red-image verification failed'
        report['passed'] = True
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        if stopped:
            restarted = time.monotonic()
            D.command('systemctl','start','glc-demo')
            deadline = time.monotonic()+120
            while time.monotonic() < deadline:
                try:
                    state = obj(RX/'_status.json')
                    if (state.get('ready_normal') and state.get('ready_fallback')
                            and float(state.get('full_ready_uptime',0)) > restarted):
                        break
                except (OSError,ValueError):
                    pass
                time.sleep(.2)
            else:
                raise RuntimeError('Production model service did not recover')
            report['restored_status'] = state
        report['radio_after'] = [p for p,a in D.clients('radio_rx_serve.py')]
        assert report['radio_after'] == report['radio_before']
        assert all(D.digest(name)==row['md5'] for name,row in expected['hashes'].items())
        report['after_fpga'] = Path('/sys/class/fpga_manager/fpga0/state').read_text().strip()
        assert report['after_fpga'] == report['before_fpga'] == 'operating'
        save(out/'guard.json', report)
        save(TASK/'current_check.json', report)
        print(json.dumps(report), flush=True)

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--worker':
        worker(Path(sys.argv[2]))
    else:
        guard()
