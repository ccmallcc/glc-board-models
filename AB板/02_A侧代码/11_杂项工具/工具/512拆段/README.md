# `工具/512拆段/` —— 把 512 的 s4 生成器切成两段的那套脚本

> **2026-10-22 晚的结论先说：这套脚本做完了、验证通过了，但在这块板上"不需要"。**
> 因为后来发现整段 s4 只要 `--lazy_load` + `--compress` 两个开关一起开就能跑（2771.2 ms）。
> 留着是因为：① 数值等价那一步（`max|full-(B∘A)| = 0`）是硬证明；
> ② 以后若 1024 上来、或 `--compress` 压不下来，拆段仍是可用手段。

## 文件

| 文件 | 干什么 |
|---|---|
| `_cut_probe_512.py` | 列 s4 的**候选切点**（单边跨段、边界 ≤32 MB，靠近中点） |
| `_cut_probe_b.py` | 在 segB 内部再找切点（若要拆成 3 段） |
| `c1_split_s4_512.py` | **主脚本**：算跨段 → `onnx.utils.extract_model` 导出两段 → 用 onnxruntime 验数值等价 |
| `fix_split_shapes.py` | **必跑**：extract_model 抄来的维度带 `batch=0`，icraft-parse 会报 `input_dim ... not same with model`；这里把 in/out 维度写死成真实值并自检 |
| `c1_split512_compile.py` | parse 两段 → 给 segB 造标定输入（用 segA 跑标定集得到跨段张量）→ `c1_pipeline.py` 走 int8 全链 |
| `cmp_xhat.py` | 把板端 dump 的 x_hat 与 PC 的 fp32 参考比（PSNR / 相对 L2） |
| `_run_split_s4.sh` | 板端串两段跑（A 的输出落到盘、再喂给 B），两段各报 hard time |

## 实测结果（2026-10-22）

| 段 | 切点 | 编译耗时 | raw | 板上 hard time |
|---|---|---|---|---|
| segA | 第 428 节点后（`blocks.14/Resize_output_0`，[1,256,128,128]=16 MB） | 131 s | 76.6 MB | **73.511 ms**（不加任何开关） |
| segB | — | 1049 s | 798 MB | 单独仍需 **5,670,699,008 B** > 4.29 GB ⇒ 还得 `--compress` |

**数值等价（两层都验了）**：
- fp32 ONNX：`max|full - (segB∘segA)| = 0.000e+00`（真实 latent）
- **板上 int8**：拆段输出 md5 `2f69f7ffb0b8ca50c48b3df136a6bc68`
  = 整段输出 md5 `2f69f7ffb0b8ca50c48b3df136a6bc68` ⇒ **逐字节相同**
- 时间：segA 73.472 + segB 2725.133 = **2798.605 ms**，整段 2771.239 ms ⇒ 拆段多花 **27.4 ms（+0.99%）**

## 踩过的三个坑（都记在这里，省得下次再撞）

1. **`extract_model` 导出的输入维度是 `batch=0`**。icraft-parse 会报
   `input_dim in toml is not same with model!` + `ShapeInfer Error: Got invalid dimensions`，
   看着像参数给错，其实是 ONNX 里那张卡片就是 0 ⇒ 必须跑 `fix_split_shapes.py`。
2. **跨段张量的通道数别照抄 shape 打印的第一版猜测**。`blocks.14/Resize_output_0` 是
   **[1,256,128,128]（256 通道）**，不是 512 —— 写错会让 segB 的 Conv 输入对不上。
3. **随机 latent 会让生成器输出 NaN**（本机实测两次都是 nan）。验数值等价必须用**真实 latent**
   （`calibref_512/calib/s4_gs_generator/00.ftmp`），否则会得到一个"nan = nan"的假结论。
