# 板端脚本（上板 / 交叉编译 / 编译环境）

> **为什么把它们放进仓库**：这些脚本原先只躺在 `E:\fudanwei\_logs\sim\`（**不在 git 里**），
> 但多份文档按那个路径引用它们 —— **队友克隆仓库后按文档找不到文件**。
> 2026-09-22 起统一归档到这里：`GLC-共享包\工具\板端脚本\`。

---

## 一、脚本清单（按用途分）

### 1. 交叉编译环境（`04_环境安装指南.md` §2）

| 脚本 | 用途 |
|---|---|
| `inventory_sdk.sh` | 列出 WSL 里 Icraft 的 cmake 包配置 / aarch64 库 / 头文件 |
| `cmake_cross_demo.sh` | 最小 cmake 交叉工程（`find_package(icraft-zg330backend)`）配置+编译+qemu 跑 |
| `xbuild_arm64.sh` | 把 `工作区\rans\*.cpp` 交叉编译成 aarch64 |
| `xbuild_and_run_arm64.sh` | 上面 + 落盘到 `工作区\rans\board_bin\` + qemu 试跑 |
| `qemu_verify_arm64.sh` | 用 qemu 跑 aarch64 回归，与 x86 结果对照 |
| `arm_vs_x86_compare.sh` | **同源码同编译器**编 x86_64 与 aarch64，逐字比对输出 |
| `tpl_build_test.sh` | 编译并验证 `开发板程序模板\{hello,bench}` |
| `crlf_proof.sh` / `crlf_which_file.sh` | ⭐ **证伪了"Makefile 的 CRLF 会挂"** —— 实测无害；真正会挂的是 `.sh` 直接执行 |

### 2. 上板（`16_板子到手第一步.md`）

| 脚本 | 用途 |
|---|---|
| `prep_scp.sh` | WSL 里装 `sshpass`、测到板子的连通性 |
| `upload_hello.sh` | 上传 `hello_arm64` 并在板上跑 |
| `upload_and_bench.sh` | 上传整套 rANS 回归包 + 跑 hello/bench/V1 |
| `w2_bench.sh` | ⭐ **W2 计时尝试**（见下方警告） |
| `readfile_bench.cpp` | 拆解 `rans_port` 耗时构成用（读+解析 vs 编码） |
| `ls_board.sh` | 列出板子上实际落了哪些文件 |
| `ssh_via_wg.sh` | ⭐ **隔着 WireGuard 登录板子**（10.88.0.3）并确认身份 |
| `start_serve_via_wg.sh` | ⭐ **隔着 WireGuard 在板上起 `icraft-serve`** |
| `wg_link_bench.sh` | ⭐ **量 WireGuard 这条路的延迟与吞吐**（结论：延迟好、带宽只有 0.31 MB/s） |
| `bundle_test.sh` / `bundle_shim_test.sh` | 在 WSL 里用 qemu 垫片模拟"包到了板上" |

### 3. NPU 部署（`17_模型部署上板.md`、`V15` 报告）

| 脚本 | 用途 |
|---|---|
| `recon_board.sh` / `recon_board2.sh` | 板子侦察（Icraft runtime / NPU 节点 / Python / `/home/work`） |
| `inspect_deb.sh` | 看清 `Icraft_3.36.1_onchip.deb` 会装什么 |
| `list_deb.sh` | 列出 onchip deb 的**全部文件**清单 |
| `list_deb_libs.sh` | ⭐ **只列库和可执行文件** —— 用来证明**板侧有 `libaxizg330aiu.so`（本地 AXI 设备）而 PC 侧没有 `axizg330aiu.dll`**，即"推理不需要网络"的根据 |
| `probe_python_npu.sh` | 探 `icraft` 的 Python API |
| `install_runtime.sh` | ⭐ **装板端 runtime（`dpkg -i` + `ldconfig`）** |
| `install_pybind.sh` | ⭐ **把 pip 的 icraft 从 3.33.1 换成 3.36.1 wheel** |
| `open_npu.sh` / `query_npu_hw.sh` | 试开 `xrt.ZG330Device()`（会段错误，见 V15 §5） |
| `check_icraft_serve.sh` | 看 `icraft-serve` / `icraft-run` 的用法 |
| `start_icraft_serve.sh` | ⭐ **在板上启动 socket 服务（端口 9981）** |
| `check_bitstream.sh` / `find_bitstream_loader.sh` | 查 PL 位流状态 |
| `cmp_npu_vs_host.py` | ⭐ **真 NPU 输出 vs HostBackend 逐位对拍**（V15 §2） |

### 4. 仿真（`15_怎么跑三套.md` §3）

| 脚本 | 用途 |
|---|---|
| `c2sim.sh` | C2 · PL 熵编码器 4 个 testbench |
| `e2sim.sh` | E2 · FPGA 入门练习 7 个 testbench |
| `run_sim.sh` | 单工程仿真（仓库 `工具\run_sim.sh` 的另一份拷贝） |

### 5. ⭐ 板端本地 NPU 全链路（`V16_板端NPU全链路实测报告.md`）

> ⚠️ 这一组与旧脚本的关键区别：**用本地 AXI 设备 `axi://zg330aiu`**，
> **推理不经过网络**（旧脚本走 `socket://` 远程驱动）。
> 板子地址也从 `192.168.0.2` 换成了 **`192.168.31.72`（直连千兆）**。

| 脚本 | 用途 |
|---|---|
| `lan_recon.sh` | 直连以太网侦察（身份 / runtime / **eth0 链路速率** / 磁盘） |
| `transfer_models.sh` | ⭐ 传 5 个子图的 `_ZG` 产物（202.8 MB）+ 计时 + md5 校验（实测 **40.2 MB/s**） |
| `smoke_board_npu.sh` | 冒烟：传 1 个子图，板上本地 AXI 跑通并拿 runtime v_id |
| `verify_board_local2.sh` | ⭐ 证明**不需要 `icraft-serve`**，且板上 NPU 输出与 PC HostBackend **逐位相同** |
| `per_subgraph_timing.sh` | ⭐ **逐子图计时**（NPU hard / 进程墙钟 / 载模型）+ **硬算子审计** |
| `timing_board.sh` | 单子图重复计时（看方差） |
| `s1_where_time2.sh` | ⭐ 拆穿 S1 那 20 s 的归属 —— **`--ocmopt` 默认值在逐一评估三套方案** |
| `board_pack.sh` | ⭐ **板端 CPU 跑真熵编码器 `glc2_pack`** 产出真 `.glc`（逐轮补齐参考长度，**工具不改**） |
| `mk_board_vec.py` | 用 compressai 对**同一份操作数**编码，生成 `rans_board` 可吃的向量 |
| `compare_rans_board.sh` | ⭐ 板端 rANS vs compressai **逐字节对拍**（实测 4/4 phase 完全一致） |
| `verify_streams.py` | ⭐ **决定性验证**：用板端自己的 scale 解码板端的流 → 逐符号还原，证明**码流本身正确** |

### 6. PC 独显对比 + 解码闭环（`V17_PC独显对比与解码闭环报告.md`）

> ⚠️ 这一组要跑在 **WSL `Ubuntu-22.04`**（只有它装了 `compressai` + CUDA 直通）。
> Windows 的 `envs\glc` **装不上 compressai**（无 MSVC、无 Windows 轮子），跑不了真编解码器。

| 脚本 | 用途 |
|---|---|
| `run_pc_bench.sh` | ⭐ **PC 全链路基准**：独显 vs CPU 跑完整 `compress_glc`/`decompress_glc`（含算术编解码） |
| `run_pc_stages.sh` | ⭐ **按阶段拆解的 PC 基准**（`V18`）——为了和板端 NPU 的数字**同口径**横比 NPU/CPU/GPU |
| `run_pc_decode_board.sh` | ⭐ **PC 解码板端产的 `.glc`**（CPU + CUDA 各跑一遍） |
| `cuda_check.py` | 确认 WSL 里 CUDA 与 compressai 可用 |
| `try_interop.sh` | 排查 WSL 能否调 Windows `.exe`（结论：**WSLInterop 未注册且无免密 sudo**） |

### 7. ⭐ C2d（CDF / 符号映射 / 倒数表 / escape）—— 2026-09-22 **完成**

> 在 **WSL `Ubuntu-22.04`** 里跑（iverilog）。RTL 在 `C2_PL熵编码器\rtl\`，
> 向量生成器在 `C2_PL熵编码器\sim\`，ROM 在 `C2_PL熵编码器\mem\`。

| 脚本 | 用途 |
|---|---|
| `c2d_verify.sh` | ⭐ **一键完整验收**：生成向量 → 展开层 tb → 联调 payload 对拍（两个向量各跑一遍） |
| `c2d_vectors.sh` | 只生成向量（真实数据 + **escape 压力**；生成器自带自检） |
| `c2d_genvec.sh` | 单个 phase 的向量生成（调试用） |
| `c2d_sim.sh` | 只跑展开层 tb |

**验收判据**：`rans_cdf + rans_enc_stream` 产出的 payload 与官方
`BoardEncoder::encode()` **逐字一致**（真实向量 15/15 字；escape 压力向量 558/558 字）。

### 8. ⭐⭐ PL 位流**热加载**（`fpga_manager`）—— 2026-09-22 **实测可用**

> **换 PL 位流不需要重启、不需要烧卡、不需要调试器。**
> 板端 Linux 自带复旦微的 FPGA manager（`CONFIG_FPGA_MGR_FMQL_FPGA=y`），
> 写 `/sys/class/fpga_manager/fpga0/firmware` 即可整体重配 PL。
> **实测 4/4 成功**；加载后 S1 `total_hard_time = 346.731 ms`（对照 346.753 ms）。

| 脚本 | 用途 |
|---|---|
| `hotload_bitstream.sh` | 板上侧：加载 `/lib/firmware/<name>.bin`，校验 `state` 与 dmesg，无参调用会列出现有 `.bin` |

**PC 侧一键**（在 `工具\` 下，不在本目录）：

```powershell
python 工具\bit_to_bin.py          my.bit  my.bin     # .bit -> .bin
python 工具\hotload_bitstream.py   --bit my.bit --board <板子IP> --smoke
```

> ⚠️ `.bin` 不是简单去头：是 **去掉 `.bit` 头（本例 144 字节）+ 按 32 位字做字节反序**。
> 已与板上原厂 `/lib/firmware/ai7030_top_disable_icap.bin` **逐字节核对（5,980,460 B，0 处不同）**。
>
> ⚠️ 热加载是**整体重配**，正在跑的板端程序会失去 PL，**必须重跑**；但**不碰启动分区，风险为零**。

---

## 二、⚠️ 使用注意

1. **都要在 WSL 里跑**：
   - 交叉编译 / 板端操作 → `wsl -d FPAI-Ubuntu2004`
   - 仿真（iverilog） → `wsl -d Ubuntu-22.04`
2. **含中文路径**，**不要从 PowerShell 直接把路径传给 `wsl.exe`**（会乱码），
   要么先 `wsl -d <发行版>` 进去再 `bash`，要么 `wsl -- bash /mnt/e/.../x.sh`。
3. **`w2_bench.sh` 的结果是无效的** —— 它量到的主要是**文本向量解析**而不是 rANS 编码。
   详见 `16_板子到手第一步.md` §8.2。**不要引用它输出的 ns/符号。**
4. 这些脚本里写死了 IP / 密码 `fmsh`。**板子的 IP 变过好几次**（`192.168.0.2` → `192.168.31.72` → **`192.168.1.2`**，2026-09-22），
   换环境要改；找不到板子时先看 PC 自己的网段：
   ```powershell
   Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' }
   foreach($i in 1..30){ if(Test-NetConnection "192.168.1.$i" -Port 22 -InformationLevel Quiet -WarningAction SilentlyContinue){"SSH: 192.168.1.$i"} }
   ```
5. ⭐ **板端 SSH 免密（2026-09-22 实测）** —— 本机 **Windows 和 WSL 都没有 `sshpass`**
   （Ubuntu-22.04 里没有，`sudo` 还要密码；paramiko 也没装）。
   **可用方案：Windows OpenSSH 的 `SSH_ASKPASS`**：
   ```powershell
   Set-Content E:\tmp\askpass.cmd "@echo off`r`necho fmsh"
   $env:SSH_ASKPASS='E:\tmp\askpass.cmd'; $env:SSH_ASKPASS_REQUIRE='force'; $env:DISPLAY='localhost:0'
   ssh -o StrictHostKeyChecking=no root@192.168.1.2 'hostname'
   ```
   `工具\hotload_bitstream.py` 内置了这个做法。

---

## 三、和 `工作区\rans\` 的关系

`工作区\rans\` 里还有一批**更早**的脚本（`run_all.sh`、`run_v5_*.sh` 等），
它们**已经在仓库的 `工具\` 目录里有对应物**，本目录不再重复。

---

### 9. ⭐ C2e（`rans_top` 端到端仿真）—— 2026-09-24 **完成**

> 在 **WSL `Ubuntu-22.04`**（iverilog）+ **`FPAI-Ubuntu2004`**（交叉编译）里跑。

| 脚本 | 用途 |
|---|---|
| `c2e_verify.sh` | ⭐ **一键验收**：`rans_top` 全路径（寄存器 → PL DDR → rANS → 写回）对拍官方 `encode()` |
| `c2e_quirk.sh` | ⭐ **直接证明**官方 `reg_ctrl.v` 的 `RFU_W3/W4` 只有 1 位（不靠读源码下结论） |
| `build_rans_board.sh` | 交叉编译板端驱动 `工具\板端程序\rans_board.cpp`（aarch64 静态） |
| `run_pc_vis.sh` | PC 侧解码板端 `.glc` 并**出图**（原图 / 重建 / 并排） |

**验收判据**：两个向量 payload 与官方 `BoardEncoder::encode()` **逐字一致**
（`real` 15/15 字；`stress` 558/558 字，`n_escape=577`、`n_bypass=1922`、`max_raw=32000`、`max_n_bypass=4` 逐项对上）。

### 10. PL 构建（出带 NPU 的完整位流）

见 **`工具\PL构建\README.md`** —— `preflight.tcl`（2 分钟前置综合）+ `build_rans.tcl`（完整位流）。

### 11. ⭐ 板端 PL rANS 驱动

见 **`工具\板端程序\README.md`** —— 寄存器映射、内存/cache 同步、容器格式、地址搜索。

