#!/bin/bash
# V7 part B: perceptual metrics for fp32 / BF16 / INT8 reconstructions.
W=/mnt/e/fudanwei/工作区
python3 "$W/tools/v7_perceptual.py" \
  --mode recon \
  --recon_dir "$W/recon_real24" \
  --out "$W/v7_recon" --device cuda 2>&1 \
  | grep -v FutureWarning | grep -v 'warnings.warn' | tail -8
echo
python3 - <<'PY'
import json, statistics as st, collections
rows = json.load(open("/mnt/e/fudanwei/工作区/v7_recon/v7_recon.json"))
by = collections.defaultdict(list)
for r in rows:
    by[r["variant"]].append(r)
print("=== 量化变体的感知指标（真 Kodak 24 张 256x256 裁剪，q0）===")
print("%-8s %8s %8s %9s %8s %8s" % ("变体", "PSNR", "MS-SSIM", "LPIPS", "DISTS", "n"))
for v in sorted(by):
    g = by[v]
    print("%-8s %8.3f %8.4f %9.4f %8.4f %8d" %
          (v, st.mean(r["psnr"] for r in g), st.mean(r["ms_ssim"] for r in g),
           st.mean(r["lpips"] for r in g), st.mean(r["dists"] for r in g), len(g)))
print()
fp = {r["stem"]: r for r in by["fp32"]}
for v in ("bf16", "int8"):
    if v not in by:
        continue
    d = [(r["lpips"] - fp[r["stem"]]["lpips"], r["dists"] - fp[r["stem"]]["dists"],
          r["psnr"] - fp[r["stem"]]["psnr"]) for r in by[v]]
    print("%-6s 相对 fp32:  ΔLPIPS=%+.5f  ΔDISTS=%+.5f  ΔPSNR=%+.3f dB" %
          (v, st.mean(x[0] for x in d), st.mean(x[1] for x in d), st.mean(x[2] for x in d)))
    print("        %s" % ("（数值为正 = 比 fp32 差）"))
PY
