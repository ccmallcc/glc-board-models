# MANIFEST —— GLC2 验收向量（INT8 链）

> 这些数字全部是**实测**。任何一项对不上，就说明你手上的东西不是这一份。

---

## 1. 向量文件（12 个，共 946,137 B ≈ 924 KiB）

| 文件 | 字节 | md5 | 说明 |
|---|---:|---|---|
| `glc/full_img0.glc` | 324 | `23148d29e133e4b9dfae5ffe99274dbe` | 容器（INT8 `_ZG` 链产出） |
| `glc/full_img1.glc` | 316 | `d4b9476b29c71d42ae66041c88ac5ce9` | 同上 |
| `glc/full_img2.glc` | 316 | `a2658789b6295571893f7cf4c1e1c293` | 同上 |
| `glc/full_img3.glc` | 312 | `eabd2cc5929678de836a11944d7257b8` | 同上 |
| `src/full_img0.png` | 128045 | `ebb42f0f587b83592bbaf04771f5150d` | 源图（256×256，kodim01 crop） |
| `src/full_img1.png` | 111204 | `3ee9bc714e8b7c47a07ef6a25bd4de16` | 源图（kodim02 crop） |
| `src/full_img2.png` | 104265 | `271bad4ae58a4fd013bedb914eb2f741` | 源图（kodim03 crop） |
| `src/full_img3.png` | 100865 | `26288ab732f4ad7935dc7d343b56d30d` | 源图（kodim04 crop） |
| `rec/full_img0.png` | 143552 | `639185ec363a3a3172c3a81b0e497bdd` | **参考解码**（同一套 INT8 `_ZG` 子图） |
| `rec/full_img1.png` | 113995 | `bc8b4699252a9d1a1070d821691963ea` | 同上 |
| `rec/full_img2.png` | 126604 | `65e97e479f55018067da8d5596a34a28` | 同上 |
| `rec/full_img3.png` | 116339 | `ae8d8d3d739283dd4cace61000ff72ae` | 同上 |

---

## 2. 期望指标

| 样本 | 容器 | bpp | PSNR（源图 vs 参考解码） |
|---|---:|---:|---:|
| 0 | 324 B | 0.03955 | **18.19 dB** |
| 1 | 316 B | 0.03857 | **22.99 dB** |
| 2 | 316 B | 0.03857 | **19.79 dB** |
| 3 | 312 B | 0.03809 | **25.42 dB** |
| **平均** | **317.0 B** | **0.03870** | **21.60 dB** |

口径：256×256、`q=0`、Kodak24 四张 256×256 crop（起点 `(0,0) (37,53) (74,106) (111,159)`）。
PSNR 为 float 域，四位小数版：18.1913 / 22.9885 / 19.7931 / 25.4205，均值 21.5984。

---

## 3. 解码必需的 INT8 `_ZG` 子图

**解码只需要 s2 / s3p1 / s3p2 / s3p3**（s1 只在编码侧用，列出来是为了让编码端也能对表）。

| 子图 | json 字节 | json md5 | raw 字节 | raw md5 |
|---|---:|---|---:|---|
| `s1_encoder_ga_hyper` | 1,247,736 | `636a7b9e361b4d4ab35534bef6323c8b` | 157,542,316 | `5ffb6b8073d683c4f207b433c0b1511a` |
| `s2_hyperdec_fusion` | 145,841 | `0cabc5be7823ee70abd9159ee64523cf` | 15,154,732 | `6d63332642d4b3904ed0a63e4fdf22db` |
| `s3_phase1` | 148,912 | `330602986116b77daaf8de3f48136a7b` | 9,427,172 | `40bd8b3b455160a9dba47e246652242d` |
| `s3_phase2` | 148,897 | `8303d357e6fdc43e3277d1acea12df29` | 9,427,172 | `ddb4164b660f1705d9e0ddee4c57e44e` |
| `s3_phase3` | 148,927 | `e0e7b9b94112917042c1caf85e438b1a` | 9,427,172 | `a5a515f0a5733a4cc688f54b98ea9e87` |

⚠️ 这八个数必须逐个对上。PC 上 `工作区\compile2\*_int8\gen\` 里的同名文件**不是同一次编译**
（`s2` 的 json 是 145,857 B / `d9dc0c6d…`），用错会得到"后端不等价"的假结论。
本向量对应的是仓库根目录 `md5.txt` 里那份（`工作区\compile_real\`）。

---

## 4. 解码必需的常量

| 文件 | 字节 | md5 |
|---|---:|---|
| `z_codebook.npy` | 16,777,344 | `6b92a024c2d4a8089846cb9dcfd2cadd` |
| `ysp_reduce_w.npy` | 786,560 | `b45b3d61fd0493cae5276a93a99aadd6` |
| `ysp_reduce_b.npy` | 1,152 | `5200c064f316ece7800e337653ca94e4` |

---

## 5. 参考解码器

`AB板/02_A侧代码/07_解码端/工具/pc_decode_selfcontained.py`

一条命令跑完四个样本：

```bash
python3 pc_decode_selfcontained.py --glc_dir glc --png_dir src --n 4 --device cuda
```

- `--glc_dir glc`：只吃容器；
- `--png_dir src`：只是为了算 PSNR，按文件名排序取第 i 个，正好对上第 i 个样本。

`rec/*.png` 是用**这一版解码器脚本**加 `--save_dir rec` 落出来的：脚本
`AB板/02_A侧代码/07_解码端/工具/pc_decode_selfcontained.py`，md5
`70552bfdd057eed911cbe5331873cbb6`，16,545 B。

> ⚠️ 这个 md5 是**脚本**的，**不是** `rec/*.png` 的 —— 四张 PNG 的 md5 见 §1 表。
> （2026-10-25 审计 Q32B 第 1 条指出此处措辞有歧义，已改。）

用别的实现产出的图不必逐字节相同，走 `verify.py` 比 PSNR 即可。

---

## 6. 复现记录（可核查）

| 时间 | 环境 | 结果 |
|---|---|---|
| 2026-09-23 | 板端 NPU（ZG330） | 4 个容器产出 |
| 2026-09-26 | PC / WSL + `icraft-run.exe` HostBackend | 自洽解码 **21.60 dB**，scales/means 与编码端 **65,536/65,536 逐位一致** |
| 2026-10-25 | 换一台机器进程重跑（torch 2.14.0+cu130） | 四个样本 PSNR **12 位小数完全一致**，平均 21.598357301518 |

> 2026-10-25 那次重跑是**关键的**：容器是 9 月的、进程是新的、torch 版本也不同，
> 仍逐位复现。这正是 fp32 参考链路做不到的事。
