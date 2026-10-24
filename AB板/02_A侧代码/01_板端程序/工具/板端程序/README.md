# 板端程序 · PL rANS 熵编码器驱动

> 把 GLC 的 `(symbols, scales)` 交给 **PL 里的 rANS 熵编码器**编码，
> 与 **CPU 参考实现**逐字节对拍，并分别计时。
> 源文件：`rans_board.cpp`（单文件，无第三方依赖）。

---

## 一、为什么不用 icraft 的 C++ API

官方 `adder_demo.cpp` 走的是 `icraft-xrt` 的 `FPAIDevice` / `defaultRegRegion()` /
`defaultMemRegion()`。我们**不走那条路**，因为板上已经有直通硬件的两样东西：

| 需求 | 用的东西 | 板上实测 |
|---|---|---|
| 读写自定义算子寄存器 | **`/dev/mem`** | ✅ 存在；`busybox devmem` 可用 |
| 同时被 CPU 和 PL 看到的内存 | **`/dev/udmabuf0`** | ✅ phys `0x30100000`，128 MB 物理连续 |
| cache 同步 | u-dma-buf 的 **sysfs** | ⚠️ `dma_coherent = 0`，**必须同步** |

好处：**不需要 icraft SDK、不需要交叉编译它的库、单文件静态可执行**。

---

## 二、⚠️ 两个必须知道的坑

### 2.1 `dma_coherent = 0` ⇒ **必须手工做 cache 同步**

不做的话 **CPU 写的数据 PL 看不到、PL 写的数据 CPU 读到旧值** —— 而且是**静默**的。
u-dma-buf 的同步接口**不是 ioctl，是 sysfs**：

```
/sys/class/u-dma-buf/udmabuf0/sync_offset     写偏移
/sys/class/u-dma-buf/udmabuf0/sync_size       写长度
/sys/class/u-dma-buf/udmabuf0/sync_direction  1=to device, 2=to cpu, 3=双向
/sys/class/u-dma-buf/udmabuf0/sync_for_device 写 1 → 刷给 PL
/sys/class/u-dma-buf/udmabuf0/sync_for_cpu    写 1 → 让 CPU 看到 PL 的写
```

（出处：板上 `/root/udmabuf/udmabuf.py` 的 `set_sync_to_device`/`set_sync_to_cpu`。）

### 2.2 寄存器区地址：**`0x40080000`**，不是 demo 里的 `0x400C0000`

`0x400C0000` 属于**另一套参考设计**（单路 PLIN+pHDMI）。我们这块的地址映射
（`fpai_demo_vivado.srcs/sources_1/bd/ps_ai/ps_ai.bd`）只有四项：

| PS 口 | 地址块 | offset |
|---|---|---|
| `BYolo_GP0` | `Reg` | `0x40000000` |
| `BYolo_GP1` | `Reg` | `0x80000000` |
| **`User_GP0`** | **`Reg`** | **`0x40080000`** ← 自定义算子寄存器 |
| `User_GP1` | `Reg` | `0x80080000` |

寄存器字节偏移 = **字下标 × 4**（`reg_ctrl` 用 `itf_ra_awaddr[17:2]` 当字下标）。

---

## 三、寄存器映射（本程序用到的）

| 名字 | 字节偏移 | 方向 | 含义 |
|---|---|---|---|
| `START` | `+0x00` | W | 写 1 启动 |
| `RFU_W0` | `+0x0C` | W | `rbase[31:0]`（**物理**字节地址） |
| `RFU_W1` | `+0x10` | W | `rsize` 拍数（1 拍 = 512 bit = 64 B） |
| `RFU_W2` | `+0x14` | W | `wbase[31:0]` |
| **`RFU_W5`** | **`+0x20`** | W | **`nsym` 真实符号数** |
| `DONE` | `+0x80` | R | bit0 = 1 表示完成 |
| `RFU_R0` | `+0x84` | R | 版本 = `0x2026_0922`（**指纹**） |
| `RFU_R2` | `+0x8C` | R | payload 字数 |
| `RFU_R3` | `+0x90` | R | `n_escape` |
| `RFU_R4` | `+0x94` | R | `n_bypass_syms` |
| `RFU_R5` | `+0x98` | R | **实测拍数**（`hp_clk` = 200 MHz 域） |
| `RFU_R6/R7` | `+0x9C/+0xA0` | R | `max_raw` / `max_n_bypass` |
| `RFU_R8/R9` | `+0xA4/+0xA8` | R | 回读 `nsym` / `{tstate, fed}` |
| `reg_ctrl ADD_VERSION` | `+0xC0` | R | 官方加法器 demo 的版本 = `0x2023_0628` |

> ⛔ **`RFU_W3`(`0x06`)/`RFU_W4`(`0x07`) 不可用** —— 官方 `reg_ctrl.v` 里它们只存
> `ra_awdata[0]`（1 位）。详见 `18_上板成果总览.md` §12.5 与
> `C2_PL熵编码器/sim/reg_ctrl_quirk_tb.v` 的直接证明。

---

## 四、数据布局（与 `rtl/rans_top.v` §data_format 一字不差）

每拍 512 bit = **16 个 32 位字**，每字一个逻辑符号，**按图像自然顺序写入**：

```
word[5:0]   = k       CDF 行号 = glc_build_index(scale)
word[31:16] = value   有符号 16 位
word[15:6]  = 忽略
```

RTL 侧 `REVERSE_IN=1` 会**倒着读拍、倒着取字**，所以 PS 只要按自然顺序写。

输出：payload 每拍 16 个字，末拍不足补 0，真实字数看 `RFU_R2`。

---

## 五、编译（WSL `FPAI-Ubuntu2004` 里）

```bash
REPO=/mnt/e/fudanwei/GLC-共享包
aarch64-linux-gnu-g++ -O2 -std=c++17 -static -Wall \
  -I"$REPO/assets/板端代码" \
  -o rans_board "$REPO/工具/板端程序/rans_board.cpp"
```

实测产物：`ELF64 / AArch64 / EXEC`，1,012,384 字节（静态，板上无需任何库）。

一键脚本：`工具/板端脚本/build_rans_board.sh`。

---

## 六、用法

```
rans_board probe --reg-base 0x40080000          # 只读版本寄存器，确认地址对不对
rans_board addr  --dir /root/glc/pack/img0 ...  # 搜 rbase 候选地址（判 PL 能摸到哪块内存）
rans_board run   --dir /root/glc/pack/img0 --glc /root/glc/pack/img0.glc
```

`run` 会对 4 个 phase 各做三件事：

1. **CPU 参考**：`BoardEncoder::encode()`，取 `bench` 次里最快的一次计时；
2. **容器对拍**：把 `.glc` 里对应的 stage payload 与 CPU 参考比 —— **先证明工装没错**；
3. **PL 编码**：跑硬件，payload 与 CPU 参考**逐字节**比，并打印
   `cyc_total`（实测拍数）、墙钟、`n_escape`、`n_bypass`。

产物：`/root/glc/pack/pl_p{0..3}.bin`（PL 产的 payload 字节流）。

> ⚠️ **`--reg-base` 与内存地址都靠实测确认**：`UserCustomOp_0` 那条 AXI 通路在
> 加密的 `AI_Mate.edif` 内部，**通到 PS DDR 还是 PL DDR 从源码看不出来**，
> 所以用"已知输入跑一遍、payload 与 CPU 参考对拍"来判定。`addr` 子命令就是干这个的。

---

## 七、GLC2 容器（`--glc` 解析用）

头长 **76** 字节（`>4sBBH17I` = `4+1+1+2+17*4`），大端：

```
[0] magic "GLC2"   [1] version   [2] q_index   [3] flags
[4] 原高 [5] 原宽 [6] 补高 [7] 补宽
[8..10] y shape   [11..13] z shape
[14] z 索引个数   [15] z payload 字节数
[16..19] 四个 stage 的字节数   [20] trailer
然后 z_payload，再依次是 4 个 stage payload，无尾部字节
```

实测 `board_img0.glc`：`76 + 28 + 60 + 60 + 52 + 48 = 324` ✓
（60 B = **15 个字**，与 C2e `real` 向量的 15 字 payload 一致。）

> ⚠️ `工具/glc2_validate.py` 的文档字符串曾把该头写成 "44 bytes" —— **是错的**，
> 实际 **76**。已在文档字符串里更正（代码一直用的是 `HEADER.size`，所以没出错）。
