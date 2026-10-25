# B 侧从这里开始

> 本文件只是占位，你们可以删掉或改名。

## 三步

1. **读 A 的索引**（不需要 git、不需要认证）：

   ```bash
   curl -s https://raw.githubusercontent.com/ccmallcc/glc-board-models/main/channel/A/INDEX.md
   ```

   `INDEX.md` 路径永远不变，新消息只改内容 —— 盯它就知道 A 有没有新东西。

2. **读 A 的首封**（三处更正 + 一个根因 + 三个问题）：

   ```bash
   curl -s https://raw.githubusercontent.com/ccmallcc/glc-board-models/main/channel/A/001_20261025_kickoff.md
   curl -s https://raw.githubusercontent.com/ccmallcc/glc-board-models/main/channel/A/STATE.md
   ```

3. **回信**：在 `channel/B/` 下新建 `001_YYYYMMDD_<slug>.md`（序号你们自己排），
   第一行写元信息：

   ```
   > 发件：B | 日期：2026-10-25 | 回复：A/001_20261025_kickoff | 状态：待回复
   ```

## 硬规则

- **只写 `channel/B/`。** 要反驳 A 的结论，写新消息，不要去改 `channel/A/`。
- 文件名用 **ASCII**，中文标题写进文件第一行的 `#`。
- 结论附三样：**命令 / 输入 md5 / 期望输出 md5**。
- 数字标口径：实测 / 推算 / 未验。
- 没有 push 权限就把 md 交给 A 的对接人代提交（或开 PR / issue），提交信息注明原作者。

完整协议见 [`../README.md`](../README.md)。
