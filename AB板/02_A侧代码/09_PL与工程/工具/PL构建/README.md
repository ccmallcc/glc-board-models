# PL 构建（把 rANS 核接进官方 NPU 工程）

> 这一组脚本**不在**仓库里运行，而是从 `E:\pl_work\` 下的工作副本运行。
> 归档在这里是为了让队友能看到**完整做法**，不必重新逆向一遍。

## 一、前提

| 需要 | 位置（本机实测） |
|---|---|
| Vivado | **`D:\xlilnx\Vivado\2018.3\`**（注意目录名拼作 `xlilnx`） |
| 复旦微 IP Patch 工具包 | `E:\JFM_Kits`（`JFM_PATH`） |
| Procise | `E:\fudanwei\Procise`（`FMSH_PROCISE_PATH`） |
| 官方工程包 | `fpai_demo_fpga.rar`（`tar -xf` 可解，Windows 自带 bsdtar 认 rar） |

## 二、两条路

### 1）`preflight.tcl` —— **2 分钟前置综合**（强烈建议先跑）

```bat
run_preflight.bat
```

只综合 `rans_top` 一个模块，回答三个问题：

1. 能不能综合掉（`while` 之类不可综合构造会在这里现形）；
2. `$readmemh` 的**绝对路径**能否解析（⚠️ 必须传 `-generic MEM_ROOT=...`）；
3. **真实资源占用** —— BRAM 是最大风险。

实测（2026-09-24）：`Block RAM Tile 96/265`、`LUT 1951/78600`，0 error / 0 critical warning。

### 2）`build_rans.tcl` —— 出完整位流（NPU + rANS）

```bat
run_build.bat
```

流程：

1. `open_project` 官方工程（**不重建**，BD/MIG/GTX/SDI 的 IP 都在里面）；
2. `add_files` 加 **4 个** rANS 文件
   （⛔ **不要**加 `reg_ctrl.v` / `pulse_cross.v` —— 工程 `rtl/adder_op/` 下已有同名模块，
   重复添加会模块重复定义；两份哈希已核对相同）；
3. `source $JFM_PATH/ip_patch/run.tcl` → `add_hook_tcl_to_prj` → `replace_7z030ai_file`；
4. `reset_run` → 综合 → 实现 → 位流
   （⚠️ **不要指定位流输出路径**，补丁会自己调 Procise 打位流补丁）。

## 三、唯一的功能改动

`rtl/ai7030_edif_top.v`：

```verilog
rans_top #(.MEM_ROOT("<绝对路径>/mem")) U_rans_top(   // 原为 adder_top U_adder_top(
```

端口一一对齐；并把官方那处**位宽不自洽**修正（`adder_top` 声明 64 位、
顶层 `User_Ddr_*` 是 512 位，靠截断"碰巧能用"；`rans_top` 按 512 位声明）。

## 四、实测结果（2026-09-24）

| 项 | 值 |
|---|---|
| 综合 | ✅ 0 error / 0 critical warning |
| 全设计资源 | LUT 24,271 (30.9%) ｜ FF 41,003 (26.1%) ｜ **BRAM 174/265 (65.7%)** ｜ DSP 25 (6.3%) |
| `AI_Mate`（NPU） | **不在黑盒列表** ⇒ 加密 EDIF 正确展开 |
| 我们占的 BRAM | 96 = `rcp_arr` 54 + `cdf_flat` 27 + payload 缓冲 16 |
