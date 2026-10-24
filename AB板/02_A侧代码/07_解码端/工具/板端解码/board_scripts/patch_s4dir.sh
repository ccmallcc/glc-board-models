#!/bin/bash
# add GLC_S4_DIR env switch to decode_board.py (ASCII only)
cd /root/glcdec || exit 1
[ -f decode_board.py.bak_4107 ] || cp decode_board.py decode_board.py.bak_4107
echo "=== before ==="
md5sum decode_board.py
python3 - <<'PY'
p = '/root/glcdec/decode_board.py'
s = open(p, encoding='utf-8').read()
old = "    's4':   (os.path.join(MODELS, 's4_int8', 's4_gs_generator_ZG')"
new = ("    's4':   (os.path.join(MODELS, os.environ.get('GLC_S4_DIR', 's4_int8'),"
       " 's4_gs_generator_ZG')")
if 'GLC_S4_DIR' in s:
    print('ALREADY PATCHED')
elif old in s:
    open(p, 'w', encoding='utf-8').write(s.replace(old, new, 1))
    print('PATCHED OK')
else:
    print('PATTERN NOT FOUND -- abort')
    raise SystemExit(3)
PY
echo "=== after ==="
grep -n "GLC_S4_DIR" decode_board.py
md5sum decode_board.py
python3 -c "import ast,sys; ast.parse(open('/root/glcdec/decode_board.py',encoding='utf-8').read()); print('syntax OK')"
echo PATCH_DONE
