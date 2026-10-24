#!/bin/bash
cd /root
python3 -u /root/glc_ui.py --dev 1 -v --sleep-after 5 --sleep-blackout 8 --script "\
sleep 8000; state; dump; \
sleep 4000; state; dump; \
sleep 6000; state; dump; \
tap 512,300; sleep 5000; state; \
quit"
