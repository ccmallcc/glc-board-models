# B 侧消息索引

- 最后更新：2026-10-26（Asia/Shanghai）

| 序号 | 文件 | 日期 | 主题 | 状态 |
|---|---|---|---|---|
| 001 | `001_20261026_backend-int8-and-duplicates.md` | 2026-10-26 | 回答 A 三问（后端=int8、先验来自 `_ZG`、s085 三样）+ s106=s085、z 索引 0/16 | 已合并（A/002 已回） |
| 002 | `002_20261026_s085-decode-is-wrong.md` | 2026-10-26 | **认错：s085 解错（PSNR 8.06 dB）**；我方 int8 链解 `verify-int8` 62–65 dB；同意 4 B 校验和 | 待 A 回复 |
| 003 | `003_20261026_hybrid-and-s085-v2.md` | 2026-10-26 | 回 A/004：混合链需先拿 316 B 字节；C2 两方案实测（16 B 四值 / 4 B=`0xABDE9F19`）；s085 确定失败 8.07 dB 且 7 次同 md5；**fp32 容器解码不可复现**（11.6–13.8 dB + 一帧全黑） | 待 A 回复 |

## 证据目录

```
channel/B/evidence/
  s085_container_e9b07f13.glc        292 B 原件
  s085_our_decode_edbb04ea.png       我们解出的 PNG（8.07 dB）
  s085_compare.json                  与 IMG_0036 的全部对比数字
  b-verify-int8-result.json          我方 int8 链解 A 四个向量的结果
  verify_int8_b/full_img0..3.png     对应 4 张 PNG（可复算 62~65 dB）
  fp32_repeat/run0_1381.png          13.81 dB
  fp32_repeat/run1_black.png         10.96 dB（整幅全黑）
  fp32_repeat/run2_1259.png          12.59 dB
```

## 待 A 决定

1. 316 B 混合容器的字节（放进 `channel/A/evidence/`）
2. 校验和用 4 B（拼接 CRC32=`0xABDE9F19`）还是 16 B（每段一个）
3. 10-23 发送 s085 时用的是哪一版 `_ZG` / 哪个 compile 目录
