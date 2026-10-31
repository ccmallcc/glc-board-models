# `red_20261031/` —— 10-31 红图后续：可离线复现的四个容器

本目录给 B 侧**离线解码**用：四个 `.glc` 都是 A 板 `glcenc_daemon` 原样产物，
**不经过无线**，因此可以把"容器本身可不可解"和"无线/会话/拼图"彻底分开。

## 文件表

| 文件 | 内容 | 源图 | 容器大小 | 容器 md5 | z | 四条流长度（实测） |
|---|---|---|---|---|---|---|
| `ctrl_good_TL.glc` | 好块（对照，未改） | `src_ctrl_good_TL.jpg`<br>md5 `5a321b6d340be4f684eb63fc37b9a00f` | 324 B | `ccad285378fb6cad60f4539b0ef28424` | 16 idx / 28 B | 64, 56, 52, 48 |
| `dark_BR.glc` | **暗块（被报"红"的那块）** | `src_dark_BR.jpg`<br>md5 `6ee68b916634d76d562edfc33b69de04` | 344 B | `73020b610bf9589c6b7459fc6ea9581e` | 16 idx / 28 B | 64, 60, 60, 56 |
| `dark_BR_brightened.glc` | **同一暗块，提亮后** | `src_dark_BR_brightened.jpg`<br>md5 `e38699a70fefb93021db5cddc1695228` | 340 B | `f16afb3c839f55586d11c35171add088` | 16 idx / 28 B | 64, 60, 56, 56 |
| `ctrl_good_TL_darkened.glc` | **好块，压暗到同样暗度** | `src_ctrl_good_TL_darkened.jpg`<br>md5 `7275525735b4f26a29d0a3f378160d46` | 332 B | `e0df3067368e51a1a1b7870609576b69` | 16 idx / 28 B | 68, 60, 56, 44 |

四张源图都是 **256×256 RGB**（实测），均值 RGB（实测，整幅算术平均）：

| 源图 | 均值 RGB | 说明 |
|---|---|---|
| `src_ctrl_good_TL.jpg` | (63.7, 59.9, 88.5) | 正常块（偏冷） |
| `src_dark_BR.jpg` | **(37.2, 33.1, 30.0)** | 很暗、略偏暖 |
| `src_dark_BR_brightened.jpg` | (102.4, 94.5, 89.4) | 对上一行逐像素 `clip(a×2.2 + 25, 0, 255)`（实测；系数 2.2 是变换参数，上表均值是变换后重新统计的） |
| `src_ctrl_good_TL_darkened.jpg` | (29.6, 27.9, 41.4) | 对正常块逐像素 `a×0.473`（uint8 截断；实测 k=0.473 由三通道总均值之比得到，故回算单通道会落在 0.465~0.468） |

## 自洽性（实测）

四个容器都满足：`76 + z_len + Σ四条流长度 == 文件长度`（324/344/340/332，全部相等，误差 0）。
头字段一致：`GLC2`、ver=2、q=0、ORIG=256×256、Z=(4,4,256)、z_count=16、z_len=28。

## 请 B 侧回报什么

1. 四个容器**分别**解码，逐张报：是否出现红/NaN、整体均值 RGB；
2. 若 `dark_BR.glc` 红，请附你们为它推出来的 per-phase scales（至少 min/max 或直方图）——
   A 侧可以拿同一块跑一份对照值出来比；
3. 若四个都正常，则说明"容器可解"，问题在**无线帧/多帧会话/拼图**那一路，A 侧改查那边。

## 复现命令（A 侧）

```bash
# 四条编码命令（A 板，实测；输出末两个数字为编码/预处理耗时，单位秒）
python3 /root/glcenc_client.py ENCBATCH /root/soak/enc c1=/root/photos/IMG_0001.jpg
# OK c1 324 ccad285378fb6cad60f4539b0ef28424 1.047 0.015
python3 /root/glcenc_client.py ENCBATCH /root/soak/enc c3=/root/photos/IMG_0003.jpg
# OK c3 344 73020b610bf9589c6b7459fc6ea9581e 1.080 0.009
python3 /root/glcenc_client.py ENCBATCH /root/soak/enc c7=/root/photos/IMG_0007.jpg
# OK c7 340 f16afb3c839f55586d11c35171add088 1.050 0.020
python3 /root/glcenc_client.py ENCBATCH /root/soak/enc c8=/root/photos/IMG_0008.jpg
# OK c8 332 e0df3067368e51a1a1b7870609576b69 1.088 0.010
```

> 相机文件名与附件名一一对应：`IMG_0001→ctrl_good_TL`、`IMG_0003→dark_BR`、
> `IMG_0007→dark_BR_brightened`、`IMG_0008→ctrl_good_TL_darkened`。
