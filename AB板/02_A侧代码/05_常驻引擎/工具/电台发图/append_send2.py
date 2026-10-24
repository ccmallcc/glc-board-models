#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把第 2 次发送（p5/p6）追加进发送记录"""
import io
import os

BASE = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(BASE, '发送记录.md')
s = io.open(p, encoding='utf-8').read()

add = '''
---

## 2026-09-22 · A 板 → 电台 · 第 2 次两张会话

| 项 | 值 |
|---|---|
| 图源 | `E:\\fudanwei\\photo\\微信图片_20261008225113_483_23.jpg`（= p5）<br>`E:\\fudanwei\\photo\\微信图片_20261008225114_484_23.jpg`（= p6） |
| 板上路径 | `/root/photo/p5.jpg`、`p6.jpg` —— 与本机**逐字节一致**（md5 已核对：`9a092195…` / `479419ff…`）|
| 位流 | **v6 rANS 位流在位**（指纹 `0x20260922`）⇒ 走 **PL rANS** 路径 |
| 编码方式 | 常驻批处理 + PL rANS（`glc_batch_rsd.py`）|

### 会话过程（实测原文）

```
AT+FREQ?    -> FREQ:470.110MHz OK
AT+SYMBOL?  -> 19.2 kbps@9.6 khz OK
AT+UART?    -> UART: banud:115200, dataBit:8, stop:1, check:N OK
AT+EXIT=1   -> 'OK'
① SESSION_BEGIN  N=2  逐张长度=[328, 308]  ✅ 已确认（0.22 s）
② [1/2] p5.glc  328 B  OK  0.58 s（第 1 次）
   [2/2] p6.glc  308 B  OK  0.54 s（第 1 次）
   进度：已发 2/2 ｜ 已确认 2/2
④ SESSION_END  sent=2 ok=2   ✅ 已确认（0.22 s）
数据段耗时 1.13 s   共 2 张   成功 2   缺 0
SESSION_DONE  ok=2/2
```

### ★ 发给 B 核对的两行

| 序号 | 文件名 | 字节 | md5 |
|---|---|---|---|
| 1 | p5.glc | 328 | `f7c103baaf793c2b433ccf06824c105a` |
| 2 | p6.glc | 308 | `198080dcb5cbbbd1bed8b5f6b23c94d8` |

### 耗时（实测）

| 环节 | 耗时 |
|---|---|
| 预处理 2 张 | ~2 s |
| 引擎载入（一次性） | 6.707 s |
| 编码 p5 / p6 | 7.47 / **0.72** s |
| AT 自检 | 8.23 s |
| **电台发送 2 张** | **1.13 s** 数据段（+ BEGIN/END 各 0.22 s）|

### ⚠️ 本次暴露并修掉的一个 bug（我自己的）

`glc_batch_rsd.py`（PL 路径）写到 `/root/glc/batch_out`，
而 `glc_batch_cpu.py`（CPU 路径）写到 `/root/glc/batch_out_cpu` ——
**`send_image.sh` 里把产物目录写死成了 `batch_out_cpu`**。

⇒ 走 PL 路径时从错误目录找产物 ⇒ 误判"**还缺 p5 p6**" ⇒ **又用单张链重编了一遍（白跑 20 秒）**。
**最终容器是对的**（兜底那条链产出正确），但白等。

**已修**：产物目录跟着所选脚本走。复测确认不再触发兜底，
编码总耗时从 **28.2 s → 8.2 s**。
'''

if '第 2 次两张会话' in s:
    print('  已记录过，跳过')
else:
    s = s.rstrip() + '\n' + add
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('  OK 发送记录已追加第 2 次')
print('DONE')
