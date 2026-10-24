#!/bin/bash
cd /mnt/e/fudanwei/工作区 || exit 2
python3 tools/export_cdf_table.py --outdir rans --ops entropy_ops 2>&1 | grep -v FutureWarning | grep -v 'warnings.warn'
