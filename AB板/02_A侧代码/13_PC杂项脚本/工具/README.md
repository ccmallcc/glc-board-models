# 工具脚本说明

> 这里是我们自己写的全部脚本（67 个）。
> **它们是可复现的证据来源**——`附录_实测报告\` 里每个数字都能用这些脚本重跑出来。

---

## ⚠️ 先读这一条：脚本里有硬编码路径

**49 个 `.py` 里有 24 个含硬编码的 `E:\fudanwei\...` 路径**（我们的工作目录）。
如果你把工作区放在别处，需要先改成你自己的路径。

```powershell
# 查出哪些脚本含硬编码路径
Select-String -Path .\*.py -Pattern 'E:\\fudanwei' -List | Select-Object Filename
```

`.sh` 脚本（`run_*.sh`）是给 **WSL** 用的，里面用的是 `/mnt/e/fudanwei/...` 形式。

---

## 一、按用途分类

### 1.1 模型拆图与编译（Icraft）

| 脚本 | 作用 |
|---|---|
| `c1_export_subgraphs.py` | **把 GLC 整网拆成 6 个子图并导出 ONNX**（核心脚本） |
| `c1_pipeline.py` | 跑 Icraft 五步流程（parse→optimize→quantize→adapt→generate），支持 `--mix_precision` |
| `c1_batch.py` | **批量编译 + 打分**（6 子图 × 3 精度）。支持 `--calib_root` / `--eval_root` 分离 |
| `c1_make_calib_refs.py` | **生成校准集与 fp32 参考量**（支持多个图片目录） |
| `c1_quantize_report.py` | 汇总 quantize 的结果 |

### 1.2 HostBackend 仿真与对拍

| 脚本 | 作用 |
|---|---|
| `hb_score.py` | 把 HostBackend dump 出来的张量与 fp32 参考对拍 |
| `hb_trace_dump.py` | **逐层**追踪 HostBackend 数值 |
| `hb_op_dump.py` | 从网络 json 里 dump 算子的关键字段 |
| `hb_layout_probe.py` | 布局探测（也是"跳过 optimize 会怎样"的最小复现） |
| `hb_conv_probe.py` / `hb_int8_mul_probe.py` | 单算子探针 |
| `hb_make_calib.py` / `hb_prepare_input.py` | 校准集 / 输入准备 |
| `hb_compare.py` / `hb_variant_test.py` / `hb_scan_nan.py` | 对比与排查 |
| `hb_onnx_scan_scalarmul.py` | 扫描 ONNX 里的 scale/mul 模式 |
| `layerwise_cmp.py` / `layerwise_map.py` | **逐层量化误差分析**与层→算子映射 |
| `make_mix_csv.py` | 生成混合精度 CSV |

### 1.3 熵编码（V1/V2）

| 脚本 | 作用 |
|---|---|
| `dump_entropy_operands.py` | **导出真实的每相位熵编码算子**（symbols / scales / means） |
| `export_cdf_table.py` | **导出板端 CDF 常量表**（紧凑格式）+ `scale→index` 验证向量 |
| `export_rans_vector.py` | 导出 rANS 测试向量（真实数据） |
| `export_rans_stress.py` | 导出压力测试向量 |
| `export_rans_board.py` / `export_rans_board_stress.py` | 导出**板端路径**向量（给 symbols + scales，不给 index） |
| `entropy_bench.py` / `entropy_bench2.py` / `entropy_multi.py` | AE/AD 耗时基准 |

> ⚠️ 熵编码相关的脚本**必须在 WSL `Ubuntu-22.04` 里跑**（compressai 装不到 Windows）。

### 1.4 量化端到端

| 脚本 | 作用 |
|---|---|
| `quant_e2e.py` | **端到端量化影响**。关键开关：<br>`--use_zg`（用**可部署产物**而非量化图，**必加**）<br>`--mix_root/--mix_tag/--mix_subs`（混合精度）<br>`--save_recon`（导出重建张量） |

### 1.5 验证与基准（V 系列）

| 脚本 | 对应 | 作用 |
|---|---|---|
| `glc2_validate.py` | —— | **GLC2 容器独立校验器**（不依赖 torch / compressai） |
| `ps_ref_state_machine.py` | T6 | PS 侧状态机 + VQ 参考实现（bit-exact 自检） |
| `v0_baseline.py` | V0 | 基准跑分（RD 曲线） |
| `v3_regression.py` | **V3** | **回归向量集**：`--make` 造黄金集，`--run` 跑回归 |
| `v4_zg_compare.py` | **V4** | **可部署产物 vs 量化图**的数值对拍 |
| `v5_dump_operands.py` | V5 | 导出容器操作数（monkeypatch 团队编解码器） |
| `v5_verify.py` | V5 | 用 compressai 解码自产容器并逐位比对 |
| `v6_kodak_baseline.py` | **V6** | **真实位流全量基准**（支持 `--crop`） |
| `v7_perceptual.py` | **V7** | **感知指标**（LPIPS / DISTS / MS-SSIM），两种模式 |
| `v8_visual_compare.py` | **V8** | 出**可视化对比图** |
| `split_timing.py` | —— | PC 侧编/解码分段计时 |
| `glc_stream.py` | **V12/V13** | **传输协议 + PC 侧收发原型**（`--selftest` 一键回环） |
| `video_cost.py` | —— | GLC-Video 成本估算 |
| `docx_extract.py` | —— | 从 docx 提取文本 |
| `html_extract.py` | —— | **从 Sphinx HTML 提取文本**（读 `Icraft-3.36.1\docs\` 官方文档用，支持代码块） |
| `board_e2e.py` | **V16** | ⭐ **板端本地 NPU 全链路**：板上 `axi://zg330aiu` 跑 5 个子图 + PC 侧 S4 解码；导出 `glc2_pack` 的操作数 |
| `pc_decode_glc.py` | **V16** | PC 侧解码板端产的 `.glc`（熵解码 + S4），量延时与 PSNR |
| `pc_decode_board.py` | **V17** | ⭐ **PC 解码板端码流（已修好模型不匹配）**，CPU/CUDA 均可（**要跑在 WSL**，需 compressai） |
| `bench_pc_chain.py` | **V17** | ⭐ **PC 全链路基准**：独显 vs CPU，含算术编解码（**要跑在 WSL**） |
| `bench_pc_stages.py` | **V18** | ⭐ **按阶段拆解**（S1/S2/S3/熵编码/熵解码/S4）——为了和板端 NPU **同口径**横比 NPU/CPU/GPU（**要跑在 WSL**） |

---

## 二、一键脚本（`run_*.sh`，在 WSL 里跑）

| 脚本 | 作用 | 期望结果 |
|---|---|---|
| `run_all_v1_v2.sh` | **V1 + V2 全部检验** | `总判定: ALL-PASS` |
| `run_v3.sh` | **V3 回归集**（造黄金集 + 跑回归） | `34/34 vectors reproduced exactly` |
| `run_regression_all.sh` | V1+V2+V5 一次跑完 | `总判定: ALL-PASS` |
| `run_v6.sh` | V6 基准（参数：输入目录 输出目录 q列表 是否存图） | 每档 `AVERAGE q0: ...` |
| `run_v7.sh` / `run_v7_recon.sh` | V7 感知指标 | 每档 `AVERAGE q0 (24 imgs): ...` |
| `run_v10.sh` | V10 512×512 基准 | 同 V6 |
| `run_v12.sh` | **V12/V13 回环自测**（参数 `1` = 同时解码） | `==== V12/V13 闭环: 通过 ====` |
| `run_v5_dump.sh` / `run_v5_pack.sh` / `run_v5_pack2.sh` / `run_v5_verify.sh` | V5 容器闭环四步 | `逐字节 vs 参考容器 : 完全一致` |

**运行示例**：

```powershell
wsl -d Ubuntu-22.04 -- bash /mnt/e/fudanwei/工作区/rans/run_all_v1_v2.sh
```

---

## 三、一键自检

```powershell
powershell -ExecutionPolicy Bypass -File "E:\fudanwei\GLC-共享包\工具\check_env.ps1"
```

检查 25 项（官方资料、Icraft 工具链、3 个 Python 环境、2 个 WSL 发行版、工作区关键产物），
并**顺带体检 Kodak 图片大小**（防止再拿错数据集）。

---

## 四、使用建议

1. **先跑 `check_env.ps1`**，确认环境没问题；
2. **动手前读 `08_踩过的坑与注意事项.md`**——尤其"量化必须独占 GPU"和"不能跳过 optimize"；
3. **改脚本前先看它有没有硬编码路径**；
4. **跑 GPU 任务时不要并行**；
5. 脚本用的是**绝对路径**，换机器要批量改（可以用上面那条 `Select-String` 先找出来）。
