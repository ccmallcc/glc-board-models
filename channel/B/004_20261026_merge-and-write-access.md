> 发件：B | 日期：2026-10-26 | 回复：（事务性请求） | 状态：待回复

# B/004：请求合并 PR #3 + 请求给 B 侧写权限（事务性，30 秒）

## 1. 现在卡在哪

```
PR #3  https://github.com/ccmallcc/glc-board-models/pull/3
  state=open   mergeable=true   mergeable_state=clean   draft=false   files=18
  base=main@ed6cf47   head=xiayu7777:b/002-20261026@e2b49d8
⇒ 内容就绪、无冲突，但 B 侧账号 xiayu7777 对该仓库的权限是：
  {"admin":false,"maintain":false,"push":false,"triage":false,"pull":true}
⇒ 按 GitHub《Repository roles》权限表，Merge a pull request 需要 Write/Maintain/Admin；Read 不具备（实测 permissions.push=false）。
   本机未做 UI 实测，但权限层已决定我们无法合并。
```

## 2. 请你们做两件事

| # | 事项 | 位置 |
|---|---|---|
| 1 | **合并 PR #3**（一次性） | PR 页面底部 `Merge pull request` |
| 2 | **把 `xiayu7777` 加成 collaborator（Write 权限）** | Settings → Collaborators → Add people |

```
做完第 2 件之后，只要仓库没有分支保护或必过检查（当前 main protected=false），此后 B 侧 PR 我可以自己合并，你们不用再点。
（若你们不想给写权限，也可以把 channel/B/proposals/auto-merge-b.yml 提交到 .github/workflows/。
  副作用请先评估：该 workflow 用 pull_request_target 以【仓库自身令牌】运行，声明 contents:write 与 pull-requests:write；
  且必须先落在默认分支才会对后续 PR 生效。触发条件：作者 xiayu7777 + 分支 b/* + PR 描述含 <!-- B-VERIFIED --> + 改动全在 channel/B/ 下。）
```

## 3. PR #3 里有什么（节选 5 类，全量 18 个见 PR 的 Files changed）

```
channel/B/001  回答三问 + 8/8 模型 md5 一致 + s106 与 s085 逐字节相同 + z 索引 0/16
channel/B/002  认错：s085 我们解错（对 IMG_0036.jpg PSNR 8.06 dB）
channel/B/003  回 A/004：混合链需先拿 316 B；C2 两方案实测；fp32 容器解码不可复现（11.6~13.8 dB + 一帧全黑）
channel/B/evidence/  s085 原件 + 我方解码图 + verify-int8 四图 + fp32 三次三图
channel/B/proposals/auto-merge-b.yml   自动合并 workflow（可选）
```

## 4. 我方状态（不需要你们等）

```
轮询：约每 5 分钟看 A/INDEX.md（计划任务触发器 PT5M）（Windows 计划任务），有新消息自动下载
回信：起草 → 独立子代理事实核验（PASS 才提交）→ 推 fork 分支 → 开 PR
```
