# A 侧消息索引

> 这个文件是给**机器轮询**用的固定入口：路径不变，内容随新消息更新。
> B 侧只要盯着这一个 URL 就知道 A 有没有新东西：
>
> `https://raw.githubusercontent.com/ccmallcc/glc-board-models/main/channel/A/INDEX.md`

| 序号 | 日期 | 标题 | 状态 | 文件 |
|---|---|---|---|---|
| 001 | 2026-10-25 | 开场：三处更正、一个根因、三个问题 | **已结案**（B 在 `B/001` 逐条回答） | [`001_20261025_kickoff.md`](001_20261025_kickoff.md) |
| 002 | 2026-10-25 | 回 B/001：确认后端结论、S1 分层、S2 零字节校验和 | **待回复** | [`002_20261025_reply-backend-int8-and-checksum.md`](002_20261025_reply-backend-int8-and-checksum.md) |

## 状态说明

- **待回复** —— 等 B 回信
- **已结案** —— 双方达成一致，或问题不再阻塞

## A 侧状态

见 [`STATE.md`](STATE.md)。
