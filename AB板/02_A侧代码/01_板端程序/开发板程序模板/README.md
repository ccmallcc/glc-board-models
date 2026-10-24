# 板端程序模板（不依赖 Icraft）

> 用途：**自己写 C++、编成开发板能跑的程序**。
> 全程只用交叉编译器 `aarch64-linux-gnu-g++`，**不碰 Icraft 的任何库**。
> 环境在 WSL 发行版 **`FPAI-Ubuntu2004`**（见 `04_环境安装指南.md` 第二节）。

---

## 一、三步走

```powershell
# ① 进环境（Windows 侧一条命令）
wsl -d FPAI-Ubuntu2004

# ② 进工程目录（WSL 里 Windows 的 E: 就是 /mnt/e）
cd /mnt/e/fudanwei/GLC-共享包/开发板程序模板/hello

# ③ 编 + 验（三个 make 目标）
make            # 编 aarch64 静态版
make file       # 必须看到 "ARM aarch64"
make run-arm    # 用 qemu 在**本机**先跑一遍，不用等板子
```

就这样。`make` 里已经封装好了交叉编译器、`-static`、qemu 的 sysroot 参数。

---

## 二、两个模板

| 目录 | 是什么 | 什么时候抄它 |
|---|---|---|
| **`hello/`** | 最小程序：打印指针宽度 / 核数 / 一个计时循环 | 只想**验证链路通不通** |
| **`bench/`** | **基准测试骨架**：warm-up + 多轮 + min/median/mean + 单次/单符号换算 | 要**测板上耗时**（W1/W2）时抄它 |

`bench` 那个模板刻意规避了板端计时的三个经典错误：

1. **只跑一次就报数** → 受 CPU 频率爬升、缓存冷启动影响。模板先跑 3 次 warm-up。
2. **只报总耗时** → 无法与别人的数字比。模板同时给 **per call / per unit**。
3. **被测循环被编译器优化掉** → 模板用 `sink` 累加回写，并把它打印出来自证。

> 📌 **必须开 `-O2`**（Makefile 里已开）。基准测试用 `-O0` 测出来的是编译器，不是硬件。

---

## 三、Makefile 怎么改成你自己的

```make
CXXFLAGS := -O2 -std=c++17 -Wall -Wextra
SRCS     := main.cpp                    # ← 多文件就都列上：a.cpp b.cpp c.cpp
OUT      := hello_arm64                 # ← 改名字
```

多文件、加头文件目录、链接自己的库：

```make
SRCS      := main.cpp rans.cpp
CXXFLAGS += -Iinclude
LDFLAGS  += -Llib -lmylib              # 注意：-l 要放在 -static 之类之后
```

**`ARCH ?= arm64` 这个开关留着**：`make ARCH=x86` 会在同一目录编一份本机版，
用来做"同一份源码，x86 与 aarch64 结果是否一致"的对照 —— 这是最省事的一种正确性验证。

---

## 四、⚠️ 四个坑

> 📌 **先纠一个常见误传**（我自己一度也这么写，实测后改掉）：
> **Makefile 的 CRLF 在 GNU Make 4.2.1 上是无害的** —— make 读 makefile 时会剥掉行尾的 `\r`，
> 实测带 CRLF 的 Makefile 编出来 `exit=0`。`.cpp` 有 CRLF 同样无害。
> **真正会挂的是 `.sh` 脚本直接执行**（见下表第 1 条）。别把时间花在不是问题的东西上。

| # | 现象 | 根因 | 对策 |
|---|---|---|---|
| **1** | `./x.sh: /bin/bash^M: bad interpreter: No such file or directory` | **`.sh` 脚本是 CRLF** 行尾，`#!` 那行的 `\r` 被当成解释器路径的一部分 | `sed -i 's/\r$//' *.sh`。<br>⚠️ 注意：`bash x.sh` **能正常跑**（bash 不用 shebang），只有 `./x.sh` 才挂 —— 所以这个错很容易只在某些调用方式下出现 |
| **2** | 从 PowerShell 传**含中文的路径**给 `wsl.exe` 全变乱码（`工作区`→`宸ヤ綔鍖`），命令**静默跑错** | PowerShell → `wsl.exe` 的参数编码 | 把命令**写进一个 UTF-8 脚本文件**，再用 **ASCII 路径**调用该脚本。本模板的 `开发板程序模板` 目录名含中文，**从 PowerShell 直接传路径就会中招**，建议先 `wsl -d FPAI-Ubuntu2004` 进去再 `cd` |
| **3** | qemu 跑动态链接程序报 `libstdc++.so.6: cannot open shared object file` | qemu-user 默认不找交叉 sysroot | 加 `-L /usr/aarch64-linux-gnu`（Makefile 里已加）；**或直接 `-static`** |
| **4** | 在 `Ubuntu-22.04` 里编的 x86 二进制拿到 `FPAI-Ubuntu2004` 里跑报 `GLIBC_2.34 not found` | 两发行版 glibc 不同（20.04 = 2.31，22.04 = 2.35） | **在哪跑就在哪编** |

---

## 五、🔴 qemu 跑出来的时间**不是板上的时间**

模板跑起来会打印耗时，**但那是 qemu 的值**：

| | x86_64 本机 | aarch64 @ qemu |
|---|---|---|
| `hello` 的 1e7 次累加 | 2.1 ms | **15.1 ms** |

**这 7 倍差的是 qemu 的二进制翻译开销，不是 A53 的速度。**
同理它报的 `hardware_concurrency = 32` 是**本机 i9 的核数**，不是板子的 4 核。

> ✅ **qemu 的用途只有一个：验证"这个二进制能不能正确跑、结果对不对"。**
> ❌ **它的耗时数字一个都不许写进报告。**
> 真实 A53 数据只能在板子上测（`06_接下来要做什么.md` 的 W1/W2）。

---

## 六、上板

| 步骤 | 做法 |
|---|---|
| 传 | `scp`（MobaXterm 自带）或 U 盘。板子 IP 在串口登录后 `ifconfig` 看 |
| 板子账号 | `root` / `fmsh`（Ubuntu 20.04 aarch64） |
| 跑 | `chmod +x ./xxx && ./xxx` |
| **建议** | **传静态版**（`-static`）——不用管板上 `libstdc++` 版本 |

---

## 七、相关

| 文档 | 关系 |
|---|---|
| `04_环境安装指南.md` §2 | 交叉编译环境的启动 / 编译 / qemu 验证 / 坑 |
| `04_环境安装指南.md` §2.4 | **要用 Icraft SDK 时**改成 `cmake` + `find_package` 的写法 |
| `assets\板端代码\` | 我们真正的板端参考实现（rANS + GLC2 容器），可交叉编译 |
| `06_接下来要做什么.md` W1/W2 | 拿到板子后要测的两个数，`bench/` 就是给它们准备的 |
