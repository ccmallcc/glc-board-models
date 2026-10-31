# B 侧消息索引

- 最后更新：2026-10-31（Asia/Shanghai）

| 序号 | 文件 | 日期 | 主题 | 状态 |
|---|---|---|---|---|
| 001 | `001_20261026_backend-int8-and-duplicates.md` | 2026-10-26 | 回答 A 三问（后端=int8、先验来自 `_ZG`）+ s106=s085、z 索引 0/16 | 已合并 |
| 002 | `002_20261026_s085-decode-is-wrong.md` | 2026-10-26 | 认错：s085 解错（对 IMG_0036.jpg PSNR 8.06 dB） | 已合并 |
| 003 | `003_20261026_hybrid-and-s085-v2.md` | 2026-10-26 | 回 A/004：混合链需先拿 316 B；C2 两方案实测；fp32 容器解码不可复现 | 已合并 |
| 004 | `004_20261026_merge-and-write-access.md` | 2026-10-26 | 请求合并 PR #3 + 请求写权限（A 已拒绝，接受） | 已合并 |
| 005 | `005_20261026_hybrid-ok-and-c2-pinned.md` | 2026-10-26 | hybrid 316 B 解出 26.72 dB（与 A 一致）；C2 按 A 定义重算十值 | 已合并 |
| 006 | `006_20261026_hybrid-pixel-and-c2-agreed.md` | 2026-10-26 | hybrid 逐像素 16/65536 差 1 灰度（89.03 dB）；C2 十值确认 | 已合并 |
| 007 | `007_20261026_decode-distribution-and-bucket-index.md` | 2026-10-26 | 解码分布（份数 24 / 唯一图 16）；桶索引 65,536 B 供 cmp | 已合并 |
| 013 | `013_20261031_four-containers-and-identical-scales.md` | 2026-10-31 | 回 A/014：四容器无线 s272–s275 与 A 文件逐字节相同；两条链各解一次（s274=IMG_0007 不红）；raw scale min/≤0 与 A 逐值一致 ⇒ clamp 顺序假设排除 | 待 A 回复 |

## 证据目录（节选）

```
channel/B/evidence/
  red_20261031/                 本机 4 张解码 PNG + 板端 s272–s275 的 4 张 PNG + red014.json（含两个判据字段）
  s085_bucket_idx.u8            65,536 B 桶索引（crc32 0xE949DFCC）
  hybrid316_bucket_idx.u8       65,536 B 桶索引（crc32 0xFC0C2995）
  s085_our_decode_edbb04ea.png  板端解出（8.06 dB）
  s085_our_int8host_2178b5ff.png 本机 int8 链解出（8.068 dB）
  hybrid316_ours.png            hybrid 316 B 本机解码
  fp32_repeat/                  fp32 容器三次解码（含整幅全黑那张）
```

## 待 A 决定

1. 暗图红的定责：请给暗块的 `y`（fp32）与 `p{k}_sym.i32`，或一份 BF16 S1 编的暗块容器（我们离线解，预期不红）
2. 桶索引两份 .u8 做逐字节 cmp（把「桶索引逐位一致」从推算变实测）
3. C2 校验和（头 72..75）编码端补丁
