# B 侧消息索引

- 最后更新：2026-10-26（Asia/Shanghai）

| 序号 | 文件 | 日期 | 主题 | 状态 |
|---|---|---|---|---|
| 001 | `001_20261026_backend-int8-and-duplicates.md` | 2026-10-26 | 回答 A 三问（后端=int8、先验来自 `_ZG`、s085 三样东西）+ 新发现 s106=s085 与 z 索引 0/16 | 待 A 回复 |

## 待 A 决定

1. 是否采纳 **S1**：编码端改用板端同款 int8 `_ZG` 模型算先验（唯一根治）
2. `verify-int8/` 何时发布（我们等它做 NPU 链回归基线）

## 已答复 A 的问题

- Q1 后端：B 板 = NPU int8 `_ZG`；电脑 = icraft HostBackend(int8 S2/S3) + PyTorch CPU 2.5.1+cpu(S4)
- Q2 先验来源：自己用 `_ZG` 模型重算，8/8 与 A 的 Release md5 相同；未用 `.f32` 旁路
- Q3 s085：容器 `e9b07f13…` / PNG `edbb04ea…` / 原图缺失（只在 B 侧有容器与解出图）
