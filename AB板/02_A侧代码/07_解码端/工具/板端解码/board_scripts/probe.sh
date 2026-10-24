#!/bin/bash
# probe decode_board.py structure (ASCII only)
echo "===== grep markers ====="
grep -n "resolve_vids" /root/glcdec/decode_board.py
grep -n "json_output_vids" /root/glcdec/decode_board.py
grep -n "def npu" /root/glcdec/decode_board.py
grep -n "SUB" /root/glcdec/decode_board.py
grep -n "s4" /root/glcdec/decode_board.py
echo
echo "===== lines 180-300 ====="
sed -n '180,300p' /root/glcdec/decode_board.py
echo
echo "===== md5 ====="
md5sum /root/glcdec/decode_board.py
echo PROBE_DONE
