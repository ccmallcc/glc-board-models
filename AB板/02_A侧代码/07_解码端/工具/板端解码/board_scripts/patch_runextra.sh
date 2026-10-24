#!/bin/bash
# add GLC_RUN_EXTRA support to decode_board.py npu() (ASCII only)
cd /root/glcdec || exit 1
python3 - <<'PY'
p = '/root/glcdec/decode_board.py'
s = open(p, encoding='utf-8').read()
mark = "    t0 = time.time()\n    p = subprocess.run(argv, cwd=run"
ins = "    argv += os.environ.get('GLC_RUN_EXTRA', '').split()\n"
if 'GLC_RUN_EXTRA' in s:
    print('ALREADY PATCHED')
elif mark in s:
    s = s.replace(mark, ins + mark, 1)
    open(p, 'w', encoding='utf-8').write(s)
    print('PATCHED OK')
else:
    print('PATTERN NOT FOUND -- abort')
    raise SystemExit(3)
PY
grep -n "GLC_RUN_EXTRA" decode_board.py
python3 -c "import ast; ast.parse(open('/root/glcdec/decode_board.py',encoding='utf-8').read()); print('syntax OK')"
md5sum decode_board.py
echo PATCH2_DONE
