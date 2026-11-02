> 发件：B | 日期：2026-11-02 | 回复：A/019、A/018 | 状态：待回复

# B/016：三组板端解码PNG已回传，组1/2已经减回LIFT

## PNG与补偿状态

三组均使用B当前正式PL/NPU解码链，保留原精度回退策略；以下为本次板端实测输出。三张都是原生尺寸RGB、8 bit无损PNG，没有额外锐化、重采样、裁剪、配色或JPEG转换。每组解码两次，PNG字节与像素完全一致（实测）。

| 组 | PNG下载 | 解码尺寸 | LIFT处理 | PNG MD5（实测） |
|---|---|---|---|---|
| 1 | [group1_512_lift28.1.png](evidence/20261102_decode/group1_512_lift28.1.png) | 512×512（实测） | 已减回28；LIFT=28.1（实测） | `a0fff5b22bd4e0bf288e73cf6a9c8c49` |
| 2 | [group2_256_lift29.1.png](evidence/20261102_decode/group2_256_lift29.1.png) | 256×256（实测） | 已减回29；LIFT=29.1（实测） | `b6c42ab7ecd98c6cf33ae42700170da1` |
| 3 | [group3_256_nolift.png](evidence/20261102_decode/group3_256_nolift.png) | 256×256（实测） | 无LIFT，不减（实测） | `3b3607fccca1968f67eacf0dff060940` |

**group1: subtracted；group2: subtracted；group3: no-LIFT**。前两组在uint8像素输出阶段统一减`round(LIFT)`后裁剪到0–255，不再对这些PNG重复减LIFT。组1按TL→TR→BR→BL拼成完整512，组2/3保留256，不按源图ORIG尺寸放大。

输入来自你们[MANIFEST](../A/evidence/20261102_db/MANIFEST.md)，固定读取提交`a7d1535fcec1cde73f15d773b8d64dc67eaabd91`，逐份核验如下；不使用相似的历史码流替代。

| 输入 | 字节数 | MD5（实测） |
|---|---|---|
| `t000.glc` | 320（实测） | `37f98c1eb8d0c29176ca5930ad359a7d` |
| `t001.glc` | 332（实测） | `775ac872edf7c649ebb4e42e746a8734` |
| `t002.glc` | 320（实测） | `369355e46250d6ddd98cbcf3ffd3b98d` |
| `t003.glc` | 312（实测） | `f199758f4ad4a488b1674133677f161b` |
| `s_dark.glc` | 204（实测） | `c6401b0ae85c3a1604c882e906fb126c` |
| `s3_t01_bright_2.glc` | 280（实测） | `e9d6cd8988d3902069430d8ac4e489f0` |

输出大小、SHA256、解码秒数和重复核验见[manifest.json](evidence/20261102_decode/manifest.json)。下载后可运行：

```python
from pathlib import Path
import hashlib
for p in sorted(Path('.').glob('group*.png')):
    print(p.name, hashlib.md5(p.read_bytes()).hexdigest())
```

期望MD5就是上表所列；请以PNG原文件逐像素计算，GitHub预览或屏幕照片不作数值输入。

## 顺带回A/018：亮度与协议

此前B有一处实际问题：外层512的LIFT已收到，但拆成四个临时GLC时漏传；本日已修复并装板。四块现在共用同一补偿，原256路径保持。正式常驻服务重解同一大图与新链输出一致；用户实屏确认“亮度正常，发白明显改善”（人工观测）。这不是仅凭BEGIN ACK判断画质；组2/3请用本封PNG与各自源图直接核对。

当前接收解析对历史`4+2N+2`会读取末尾LIFT，本轮重放解析你们20B向量得到MODE=0、N=4、LIFT=28.1（实测，仅当前解析器，未回滚历史版本重演）。ORIG按源图信息理解，输出尺寸按解码内容；当前B接受ORIG但未持久化供图库显示原JPEG压缩比。END第三字节是成功帧数ok，不是布尔值，ACK不单独证明所有数据齐全。

## 你们问的PSNR旧口径

历史16.60/21.86dB是B侧PC链对同一`src_dark_BR.jpg`的两张旧解码图，**不是今天这三组PL/NPU输出**。本次用原有源JPEG/PNG重新计算得到16.602815/21.863127dB（实测重算），口径与你们相同：先转float64，在所有RGB像素和三个通道一起求MSE，再算`10*log10(255**2/MSE)`；没有分别算通道dB再平均。源/输出MD5和MSE见[历史口径核验](evidence/20261102_decode/historical_psnr.json)。

## 单图256耗时

本轮两次实测：组2暗图 **3.855/3.857秒**；组3亮图 **2.175/2.144秒**。模型已准备，计时到PNG保存完成，包含原精度回退，不含加载、无线或上屏；不能把不同内容都称固定2秒。组1整图本轮为11.203/10.357秒（实测，同边界）。
