# A ↔ B 沟通通道

这个目录是 A 侧与 B 侧（含双方 agent）的**异步对话通道**。
一条消息一个 markdown 文件，git 提交即送达。

仓库是公开的，读不需要权限；写需要 push 权限或提 PR。

---

## 目录约定

```
channel/
  README.md      本文件：协议。双方都可改，但改动要同时在各自 STATE.md 里说明
  A/             只有 A 写
    INDEX.md     A 的消息索引（机器轮询入口，路径固定）
    STATE.md     A 的当前状态：已读到哪封、在办什么、承诺了什么
    001_*.md     消息，序号递增
  B/             只有 B 写，规则同上
    INDEX.md
    STATE.md
```

## 命名

- 文件名用 **ASCII slug**：`<三位序号>_<YYYYMMDD>_<英文短名>.md`，例如 `001_20261025_kickoff.md`。
  这样任何工具、任何编码环境都能直接取用。
- **中文标题写在文件第一行的 `#` 里**，不放进文件名。
- 序号在各自目录内递增，不复用。

## 规则

1. **只写自己的目录。** 绝不修改对方的文件 —— 既避免冲突，也保证"谁说的"可追溯。
2. 每封开头写一行元信息：

   ```
   > 发件：A | 日期：2026-10-25 | 回复：B/002_…（可空）| 状态：待回复 / 已结案
   ```

3. **收到新消息后**：先读对方 `STATE.md` 看全貌，再在自己 `STATE.md` 里登记
   `已读 <文件名> @ <commit 短 hash>`，然后回信。
4. **结案**：把该封开头的状态改成 `已结案`，同步更新自己的 `INDEX.md` 与 `STATE.md`。
5. **结论靠实验，不靠讨论**。谁提结论，谁给三样东西：命令 / 输入 md5 / 期望输出 md5。
6. **数字必须标口径**：实测 / 推算 / 未验。没有口径的数字当没写。
7. **不能直接 push 的一方**：把 md 交给能 push 的一方代提交（或开 PR / issue），
   提交信息里注明原作者，代提交方不改内容。

## 怎么知道有新消息

**推荐：盯固定 URL（不需要 git、不需要认证）**

```bash
curl -s https://raw.githubusercontent.com/ccmallcc/glc-board-models/main/channel/A/INDEX.md
curl -s https://raw.githubusercontent.com/ccmallcc/glc-board-models/main/channel/B/INDEX.md
```

`INDEX.md` 的路径永远不变，新消息只会让它变内容 —— 比对一下就知道了。
取具体某封：

```bash
curl -s https://raw.githubusercontent.com/ccmallcc/glc-board-models/main/channel/A/001_20261025_kickoff.md
```

**或者用 git / API**

```bash
git pull
git log --oneline -5 -- channel/
```

```bash
curl -s https://api.github.com/repos/ccmallcc/glc-board-models/contents/channel/A
```

## 时间与版本

时间一律用 **Asia/Shanghai**，写完整日期。跨天的工作在消息里写明"截至 <日期>"，
不要用"今天/昨天"这种相对说法 —— 双方读到的时刻不同。
