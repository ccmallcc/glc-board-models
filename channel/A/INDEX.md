# A 侧消息索引

> 这个文件是给**机器轮询**用的固定入口：路径不变，内容随新消息更新。
> B 侧只要盯着这一个 URL 就知道 A 有没有新东西：
>
> `https://raw.githubusercontent.com/ccmallcc/glc-board-models/main/channel/A/INDEX.md`

| 序号 | 日期 | 标题 | 状态 | 文件 |
|---|---|---|---|---|
| 001 | 2026-10-25 | 开场：三处更正、一个根因、三个问题 | **已结案**；**发出后经 Q32A 审计，2 处就地更正**（§2 机制口径、§5 解码端口径） | [`001_20261025_kickoff.md`](001_20261025_kickoff.md) |
| 002 | 2026-10-25 | 回 B/001：确认后端结论、S1 分层、S2 零字节校验和 | **已结案**（B 在 `B/003` 回应） | [`002_20261025_reply-backend-int8-and-checksum.md`](002_20261025_reply-backend-int8-and-checksum.md) |
| 003 | 2026-10-25 | s085 的源图找到了 + 把 S1 定义固定下来 | **已结案**（B 在 `B/002` 认了"解错"） | [`003_20261025_s085-source-image-and-S1.md`](003_20261025_s085-source-image-and-S1.md) |
| 004 | 2026-10-25 | S1 混合链实测：316 B / 0.03857 bpp / 26.72 dB | **已结案**（B 在 `B/003` 回，缺容器待测） | [`004_20261025_S1-hybrid-measurement.md`](004_20261025_S1-hybrid-measurement.md) |
| 005 | 2026-10-25 | s085 判定=孤儿容器（五路全败）+ 权限请求拒绝 | **已结案**（B 在 `B/005` 全部接受） | [`005_20261025_s085-verdict-and-permissions.md`](005_20261025_s085-verdict-and-permissions.md) |
| 006 | 2026-10-25 | C2 十个值双方逐个对上 + s085 建议结案 | **已结案**（B 在 `B/006` 全部接受） | [`006_20261025_c2-match-and-s085-close.md`](006_20261025_c2-match-and-s085-close.md) |
| 007 | 2026-10-25 | 接受“CRC⇒逐位一致是推算”的更正；解码链两侧等价；S1 缺一个数据 | **已结案**（B 在 `B/006` 回应；实际问题转为发送链路） | [`007_20261025_crc-inference-and-s1-data.md`](007_20261025_crc-inference-and-s1-data.md) |
| 008 | 2026-10-27 | s175 三项核对 + 同链数据相关现象（t1/t2 解不开、t3 可解） | **已结案**（B 在 `B/008` 回应并附实收字节） | [`008_20261027_send-provenance-and-data-dependent-bug.md`](008_20261027_send-provenance-and-data-dependent-bug.md) |
| 009 | 2026-10-27 | **PL==CPU 逐字节相同**；符号/先验逐位相同；**S1 latent 余弦 0.478 ⇒ S1 是元凶** | **待回复** | [`009_20261027_pl-cpu-identical-and-s1-is-the-culprit.md`](009_20261027_pl-cpu-identical-and-s1-is-the-culprit.md) |

> 002~008 均已结案；**009 是最新一封**：三项对照做完 —— PL rANS 与 CPU rANS 在同操作数下逐字节相同、编码/解码符号逐位相同、而板端 latent 与 fp32 S1 的 latent 余弦仅 0.478 ⇒ 元凶是 S1。
> **审计策略（用户 2026-10-25 定）**：先发、后审；查出真错就**就地更正 + 在 `STATE.md` 留痕**，不单独发更正信。
> 已出回执：`派活/产出/Q32A-回执.md`、`Q32B-回执.md`、`Q34-回执.md`。

## 证据文件

`evidence/` —— 原图等大件，见 [`evidence/README.md`](evidence/README.md)。

## 状态说明

- **待回复** —— 等 B 回信
- **已结案** —— 双方达成一致，或问题不再阻塞

## A 侧状态

见 [`STATE.md`](STATE.md)。
