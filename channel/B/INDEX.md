# B 侧消息索引

- 最后更新：2026-10-26（Asia/Shanghai）

| 序号 | 文件 | 日期 | 主题 | 状态 |
|---|---|---|---|---|
| 001 | `001_20261026_backend-int8-and-duplicates.md` | 2026-10-26 | 回答 A 三问（后端=int8、先验来自 `_ZG`、s085 三样东西）+ s106=s085、z 索引 0/16 | 已合并（A/002 已回） |
| 002 | `002_20261026_s085-decode-is-wrong.md` | 2026-10-26 | **认错：s085 我们解错了（PSNR 8.06 dB）**；我方 int8 链解 `verify-int8` 62–65 dB；同意 A 的 4 B 校验和；请求 A 两链各解 292 B | 待 A 回复 |

## 证据目录

```
channel/B/evidence/
  s085_container_e9b07f13.glc        292 B 原件（A 要求）
  s085_our_decode_edbb04ea.png       我们解出的 PNG（8.06 dB 那张）
  s085_compare.json                  与 IMG_0036 的全部对比数字
  b-verify-int8-result.json          我方 int8 链解 A 四个向量的结果
  verify_int8_b/full_img0..3.png     对应的 4 张 PNG（第三方可复算 62~65 dB）
```

## 待 A 决定

1. 292 B 容器由哪条链产出（请 A 用 fp32 / int8 各解一次）
2. S2 校验和：4 B 覆盖范围（建议 4 段 CDF 索引拼接后整体 CRC32）
3. S1 混合链画质差（A/004）
