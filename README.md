# GLC 板端模型（ZG330 量化产物）+ 解码一致性校验向量

本仓库给 **B 端**用，三件事：

1. **板端模型**：A 侧板子上跑的那 10 个 `*_ZG.json/.raw`，**逐字节一致**（有 md5 表可核）。
   体积约 202 MB，放在 **Releases** 里（`glc_models_20261024.tar.gz`），不在 git 历史里。
2. **解码一致性校验向量**：两组，口径不同，**不能混用** ——
   [`verify/`](verify/README.md)（fp32 参考链，308 B / 26.61 dB）与
   [`verify-int8/`](verify-int8/README.md)（板端 int8 链，312–324 B / 21.60 dB）。
3. **双方沟通通道**：`channel/` —— A 写 `channel/A/`，B 写 `channel/B/`，一条消息一个 md。
   规则见 [`channel/README.md`](channel/README.md)。

> 📌 **2026-10-25 有重大更正**：校验向量原先是 CUDA 上编的，换计算后端就解不开。
> 已在 CPU 上重编（容器仍 308 B / 26.61 dB），详见 `channel/A/001_…` 与 `verify/README.md`。

---

## 一、模型文件（Release 资产）

**下载**（52 MB 压缩包，解压后约 202 MB）：

<https://github.com/ccmallcc/glc-board-models/releases/download/v2026.10.24/glc_models_20261024.tar.gz>

| 项 | 值 |
|---|---|
| 压缩包大小 | **54,879,881 B**（52.3 MB） |
| 压缩包 md5 | **`caeecddb0166f81e93c70cfbfc1eafe2`** |

解压后 `models/` 里的 10 个文件：

| 文件 | 字节 | md5 |
|---|---|---|
| `s1_encoder_ga_hyper_ZG.json` | 1,247,736 | `636a7b9e361b4d4ab35534bef6323c8b` |
| `s1_encoder_ga_hyper_ZG.raw` | 157,542,316 | `5ffb6b8073d683c4f207b433c0b1511a` |
| `s2_hyperdec_fusion_ZG.json` | 145,841 | `0cabc5be7823ee70abd9159ee64523cf` |
| `s2_hyperdec_fusion_ZG.raw` | 15,154,732 | `6d63332642d4b3904ed0a63e4fdf22db` |
| `s3_phase1_ZG.json` | 148,912 | `330602986116b77daaf8de3f48136a7b` |
| `s3_phase1_ZG.raw` | 9,427,172 | `40bd8b3b455160a9dba47e246652242d` |
| `s3_phase2_ZG.json` | 148,897 | `8303d357e6fdc43e3277d1acea12df29` |
| `s3_phase2_ZG.raw` | 9,427,172 | `ddb4164b660f1705d9e0ddee4c57e44e` |
| `s3_phase3_ZG.json` | 148,927 | `e0e7b9b94112917042c1caf85e438b1a` |
| `s3_phase3_ZG.raw` | 9,427,172 | `a5a515f0a5733a4cc688f54b98ea9e87` |

**先核 md5 再用**：

```bash
cd models && md5sum -c ../md5.txt
```

> ⚠️ 注意：网上常见的另一套 `compile2/*_int8/gen/` 产物**不是**板子上这一份
> （s1 的 `.raw` 差 3 KB，全部 md5 都对不上）。本仓库这份是**与板子逐字节一致**的
> `compile_real` 那套，2026-10-24 用 md5 逐项核对过（10/10 命中）。

---

## 二、解码一致性校验向量（fp32 参考实现）

`verify/` 里五个文件：

| 文件 | 是什么 |
|---|---|
| `IMG_0036.glc`（308 B） | 容器，md5 `5b2a4571e1f605d36a3193c1b354eaed` |
| `IMG_0036.jpg`（21 KB） | 原图（256×256） |
| `rec.png`（118 KB） | 参考解码，md5 `efa552aa939448244a894f87ddf60969` |
| `decode.py` | 参考解码器：只吃 `.glc`，自己重推 scales/means |
| `verify.py` | 比对你的解码（零依赖） |

**参考值：0.03760 bpp / PSNR 26.61 dB**（308 B / 65,536 像素）。

### ⚠️ 必须在 CPU 上解

`GLC2` 容器不存 scales/means，解码端必须重算，**且必须与编码端逐位一致**，
否则 rANS 状态机整段失步。而不同计算后端的卷积结果不一样。实测（2026-10-25）：

| 容器产自 | 解码设备 | 结果 |
|---|---|---|
| CUDA | CUDA **新进程** | **NaN** |
| CUDA | CPU | 12.84 dB |
| **CPU（本向量）** | **CPU 新进程** | **26.61 dB** ✅ |
| CPU（本向量） | CPU 单线程 | 26.61 dB，PNG **md5 完全相同** |
| CPU（本向量） | CUDA | NaN |

**cuDNN 的算法自动选择不是跨进程确定的**，所以 CUDA 产的容器连 CUDA 自己新开进程
都解不开；CPU 路径相反，跨进程、跨线程数都逐位一致。

> 📌 2026-10-24 发布的那份 308 B（md5 `a267448b…`）是在 CUDA 上编的，**已撤回**。
> 本向量在 CPU 上重编，容器字节数不变（308 B），`rec.png` 与旧版**最大只差 1 个灰度**
> （PSNR 64.14 dB），对原图仍是 **26.61 dB**。所以已发布的对比图与数字都不用改。

### 怎么验

**第一档 —— 只看图对不对（零依赖，不需要模型）**

```bash
python verify.py 你们的解码.png
```

和 `rec.png` 比 PSNR：**≥40 dB** 逐像素一致；**32–40 dB** 先验对上了但 S4 实现不同；
**<32 dB** 解错了。实测失步时落在 **12–15 dB**，完全解不开是 NaN。

**第二档 —— 从容器自己解一遍（要模型）**

```bash
python decode.py IMG_0036.glc --img IMG_0036.jpg --out my_rec.png
```

结果应与 `rec.png` **逐字节相同**，PSNR 26.61 dB。
前置：GLC 官方参考实现 + `GLC_image.pth.tar`（md5 `41453cd3f45dcd505ef637d754df76cd`，
667,371,692 B）。`decode.py --device cuda` 会直接报错退出。

### 这个向量不证明什么

1. **不证明跨计算后端可解** —— 见上表。这是 `GLC2` 格式的边界，不是实现 bug。
2. **不证明板端 int8 链能解** —— 板端跑的是 INT8 `_ZG` 子图，与 fp32 参考实现
   不是同一套先验。板端那套需要另一组"int8 产出、int8 解出"的向量
   （实测平均 21.60 dB，口径与 26.61 dB 不同，**不能混用**）。
3. **只跑了 1 张图、只跑 `q=0`。**

---

## 三、容器格式（自查用）

```
76 B 头： "GLC2" | ver(2) | q_index | flags | H,W,padH,padW,
          yC,yH,yW, zC,zH,zW | z_count | z_pay_len | 4×u32 流长度 | 0
后面是 1 段 z 索引（14 bit 定宽）+ 4 条 rANS 流
```

`256×256` 输入时：y 是 256×16×16，z 是 256×4×4 → 16 个索引 = 28 B；
4 条流合计 204 B；加 76 B 头 = **308 B**。

---

## 四、常见问题

**Q：为什么不直接放进 git？**
A：单个 `.raw` 150 MB，超过 GitHub 单文件 100 MB 硬限制；走 Git LFS 会消耗带宽配额。
放 Release 资产（单文件上限 2 GiB）既不受限、下载也不算 LFS 配额。

**Q：模型能在 PC 上用吗？**
A：能用，但要 Icraft 运行时（`icraft-run.exe`，HostBackend 后端）。
PC 上的 PyTorch 参考权重 `GLC_image.pth.tar`（667 MB）是**另一条链路**，
和这套 `_ZG` 不通用 —— 混着用必然失步。

**Q：PSNR 26.61 我复现不出来？**
A：先确认是不是在 CPU 上解的（见 §二那张表）。CUDA 上解是 NaN。

**Q：我们只需要解码，需要全部 10 个文件吗？**
A：**fp32 校验向量一个都不用**，它只要 `GLC_image.pth.tar`。
那 10 个 `_ZG` 是板端 int8 链路用的，是另一套东西。

**Q：Tier 2 跑出来报 `拿到 0 个 v_id`？**
A：那是 int8 那套解码器的事。多半是 WSL 的 Windows interop 掉了，
`icraft-run.exe` 其实报了 `Exec format error` 但 stdout 被吞了。
跑一次 `wsl --shutdown` 让它自己重新注册 binfmt 即可（**别手工注册**）。
