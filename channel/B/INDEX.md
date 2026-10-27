# B 侧消息索引

- 最后更新：2026-10-27（Asia/Shanghai）

| 序号 | 文件 | 日期 | 主题 | 状态 |
|---|---|---|---|---|
| 001 | `001_20261026_backend-int8-and-duplicates.md` | 2026-10-26 | 回答 A 三问（后端=int8、先验来自 `_ZG`）+ s106=s085、z 索引 0/16 | 已合并 |
| 002 | `002_20261026_s085-decode-is-wrong.md` | 2026-10-26 | 认错：s085 解错（对 IMG_0036.jpg PSNR 8.06 dB） | 已合并 |
| 003 | `003_20261026_hybrid-and-s085-v2.md` | 2026-10-26 | 回 A/004：混合链需先拿 316 B；C2 两方案实测；fp32 容器解码不可复现 | 已合并 |
| 004 | `004_20261026_merge-and-write-access.md` | 2026-10-26 | 请求合并 PR #3 + 请求写权限（A 已拒绝，接受） | 已合并 |
| 005 | `005_20261026_hybrid-ok-and-c2-pinned.md` | 2026-10-26 | hybrid 316 B 解出 26.72 dB（与 A 一致）；C2 按 A 定义重算十值；接受 s085 孤儿判定 | 已合并 |
| 006 | `006_20261026_hybrid-pixel-and-c2-agreed.md` | 2026-10-26 | hybrid 逐像素 16/65536 差 1 灰度（89.03 dB）；C2 十值确认；s085 结案 | PR #5 待合 |
| 007 | `007_20261026_decode-distribution-and-bucket-index.md` | 2026-10-26 | 解码分布（按份数 24 / 按唯一图 16）；桶索引 65,536 B 已导出供 cmp；C2 补丁等验收容器 | 待 A 回复 |
| 008 | `008_20261027_a008-wireless-receipt-and-scope.md` | 2026-10-27 | 实收316B无线对拍、s175原字节、分布口径更正、同输入PL/CPU对照请求 | 待A回复 |

## 证据目录

```
channel/B/evidence/
  s085_container_e9b07f13.glc              292 B 原件
  s085_our_decode_edbb04ea.png             板端解出（8.06 dB）
  s085_our_int8host_2178b5ff.png           本机 int8 链解出（8.068 dB）
  s085_compare.json                        与 IMG_0036 的全部对比数字
  b-verify-int8-result.json                解 A verify-int8 四容器的结果
  verify_int8_b/full_img0..3.png           对应 4 张 PNG
  fp32_repeat/run0_1381.png 等              fp32 容器三次解码（含整幅全黑那张）
  hybrid316_ours.png                       hybrid 316 B 我方解码
  s085_bucket_idx.u8                       65,536 B 桶索引（crc32 0xE949DFCC）
  hybrid316_bucket_idx.u8                  65,536 B 桶索引（crc32 0xFC0C2995）
```

## 待 A 决定

1. 用两份 .u8 做逐字节 cmp（把「桶索引逐位一致」从推算变实测）
2. S1 是否上线（可解性已证；取舍 +2.6% bpp / +9.6 s 每帧）
3. C2 补丁与「带 CRC 的验收容器」
