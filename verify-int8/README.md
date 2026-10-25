# GLC2 校验向量 —— INT8 链（板端 / NPU）

四个 256×256 的 GLC2 容器（312–324 B）＋ 配对源图 ＋ 参考解码。
容器由**板端 INT8 `_ZG` 链**产出，参考解码由**同一套 INT8 `_ZG` 子图**解出。

```
glc/full_img{0..3}.glc    容器
src/full_img{0..3}.png    源图（编码器的输入）
rec/full_img{0..3}.png    参考解码（解码器的输出，用它比对）
check.py                  Tier 1：查指纹 + 重算 PSNR（零依赖）
verify.py                 Tier 3：比对你的解码输出
MANIFEST.md               全部 md5 与期望值
```

---

## 这个目录和 `verify/` 是什么关系

仓库里有**两组**向量，各自对应一种计算后端，**口径不同，不能混用**：

| | `verify/`（fp32 参考） | **`verify-int8/`（本目录）** |
|---|---|---|
| 容器产自 | PyTorch **CPU fp32** | **板端 NPU int8 `_ZG`** |
| 参考解码产自 | 同一套 CPU fp32 | 同一套 int8 `_ZG` 子图 |
| 容器 | 308 B | 312–324 B |
| bpp | 0.03760 | 0.03870 |
| PSNR（对原图） | **26.61 dB** | **21.60 dB**（4 样本平均） |
| 谁该用它 | 手上有 PyTorch + 667 MB 权重的人 | 手上有 `_ZG` 子图 + Icraft 运行时的人（**= B 侧**） |

**跨着用必然失败**：int8 链解 fp32 容器 = 整段失步（B 侧实测 13.19 dB）；
fp32 链解 int8 容器 = NaN（A 侧实测）。原因见下。

---

## 为什么必须同源

`GLC2` 容器**不存 scales/means**，只存 z 的 16 个索引（28 B）。
解码端必须自己从 `z_hat` 把每个相位的熵参数重推出来，**且必须与编码端逐位一致** ——
rANS 是顺序状态机，第 i 个符号的 CDF 错一格，后面整段就废。

B 侧实测的先验误差容限：ε=1e-7 时输出基本不变，**ε=1e-6 就有 99% 像素变化**。
int8 量化误差远大于 1e-6，所以跨后端解码不是"偶尔错"，是"必然错"。

**整数运算才是可跨实现复现的那一侧** —— 同一套 `_ZG` 文件，板端 NPU 与 PC 上的
HostBackend 实测逐位相同（`s2` 输出 65,536/65,536，max|diff| = 0）。
所以本目录的向量能在"所有跑这套 `_ZG` 的实现"之间通用。

---

## 三档校验

### Tier 1 —— 零依赖

```bash
python check.py
```

校验 12 个文件的 md5，再用源图与参考解码重算 PSNR，应得：

```
样本 0  18.19 dB   样本 1  22.99 dB   样本 2  19.79 dB   样本 3  25.42 dB   平均 21.60 dB
```

证明"你拿到的是同一份文件、公开数字是真的"。**它不解码容器。**

### Tier 2 —— 需要 `_ZG` 模型 + Icraft 运行时

```bash
python3 "AB板/02_A侧代码/07_解码端/工具/pc_decode_selfcontained.py" \
        --glc_dir verify-int8/glc --png_dir verify-int8/src --n 4 --device cuda
```

**只喂 `.glc`**，不喂任何 scales/means 旁路。解出来的图应与本目录 `rec/` **逐字节相同**。
这一档证明**容器本身可独立解码**。

所需模型与常量的 md5 见 `MANIFEST.md` §3/§4。门槛在 Icraft 运行时（私有工具链），不在数据。

### Tier 3 —— 你自己的解码器

```bash
python verify.py 你的解码.png        # 自动挑最接近的样本
python verify.py 你的解码.png 2      # 指定样本
```

| PSNR vs `rec/` | 判定 |
|---|---|
| ≥ 40 dB | PASS，逐像素基本一致 |
| 32–40 dB | PASS（有差异），通常是 S4 生成器实现不同 |
| < 32 dB | FAIL |

参考尺度：先验失步落在 13–15 dB，完全解不开是 NaN。32 dB 离两边都远。

---

## 边界（别外推）

1. **不证明"任意实现都能解开 GLC2"** —— 这个命题对格式本身不成立，见"为什么必须同源"。
2. **只跑了 4 张图、只跑 `q=0`**。
3. **没逐算子比对全部中间张量**：验的是四相位 scales/means（4 样本 × 4 相位，65,536/65,536 逐位一致）与端到端 PSNR。
4. **HostBackend == 真板** 只在 `s2` 的一个输出上做过逐位对照，不能外推。
5. Tier 2 需要私有工具链，外部评审多半只能跑 Tier 1。

---

## 跑 Tier 2 之前先看这一条

WSL 的 Windows interop 会**无声消失**，`icraft-run.exe` 实际报
`cannot execute binary file: Exec format error`，但解码器只会报 `拿到 0 个 v_id`
（exe 的 stdout 被吞了）。遇到就跑：

```bash
wsl --shutdown     # 让 /init 自己重新注册 binfmt，别手工注册
```

2026-10-25 一天内踩了两次。
