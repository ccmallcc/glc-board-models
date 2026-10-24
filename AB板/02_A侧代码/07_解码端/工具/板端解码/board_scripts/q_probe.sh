#!/bin/bash
echo "===== glc_board_full.py: argparse / q ====="
grep -n "add_argument" /root/glc/glc_board_full.py
echo "--- q mentions ---"
grep -n "q_index\|qidx\|quality\|QUANT\|quant" /root/glc/glc_board_full.py | head -30
echo
echo "===== how the container q_index is set ====="
grep -n "q_index" /root/glc/glc_board_full.py | head -20
echo
echo "===== ref_stage / pack dirs ====="
ls -l /root/glc/ | head -30
echo
echo "===== is there a q table / assets ====="
ls -l /root/glc/assets 2>/dev/null | head
find /root/glc -maxdepth 2 -name "*q*" -o -maxdepth 2 -name "*quant*" 2>/dev/null | head -10
echo QPROBE_DONE
