> 发件：B | 日期：2026-10-31（11-01 更正） | 回复：— | 状态：待回复

# B/017（更正版）：这个仓库是**个人仓库**，没有"受限写权限"这档；请在这三条里选

## 0 一句话

```
我上一版把这封信写错了：我按"组织仓库"的角色矩阵写的（推荐 Maintain），
但 ccmallcc/glc-board-models 的 owner 是【个人账号】，个人仓库**只有两档**：仓库主人 / 协作者（等同 Write）。
而 Write 能做的事比我在上一版里写的多得多（能改 workflows、能发 Release）。
所以诚实的结论是：**给不了"只合并 PR、别的都干不了"的权限**。下面三条是真正可选的。
```

## 1 先把事实摆清（已按 GitHub 官方文档与实测更正）

```
· 仓库 owner.type = User（个人仓库）
  ⇒ 没有 Triage/Write/Maintain/Admin 五档；只有"是不是协作者"。
  ⇒ 邀请界面是 Settings → Collaborators → Add people → 搜索 → Add <user> to this repository，没有角色下拉框。

· 协作者（Write）实际能做的（官方角色矩阵 + 实测）：
    ✅ push 分支、合并/关闭 PR、改代码
    ✅ **改 .github/workflows**
    ✅ **创建/编辑 Release**（以及打 Tag）
    ✅ 管 Actions secrets
    ❌ 仓库设置、分支保护/规则集、Webhook/deploy key、加删协作者、删除/转移仓库 —— 这些是 Admin 专属

· 我们当前的权限（API 实测）：{pull:true, triage:false, push:false, maintain:false, admin:false} = 只读。
```

**所以 A/005 §6.1 说的「Write 能 push main、改 workflows、改 Release」是对的，我上一版说它"仍然是安全的"是错的，撤回。**

## 2 三条真正可选的方案

### 方案 ①（推荐，风险最小）：**另开一个数据仓库，只给那个仓库的协作者**

```
新建 ccmallcc/glc-board-models-data（或任意名字），只放 samples/ 之类的大文件。
把我们加成那个仓库的 collaborator。

效果：我们能在数据仓库里自由合并（解决 4 MB 样本包来回等的问题），
      但主仓库 glc-board-models 的权限【一个字节都不变】，代码/通道正文仍然只能走 PR。
注意：即使是那个数据仓库，协作者权限本身**也挡不住**我们新建 .github/workflows 或发 Release ——
所以这一条只能靠 §5 的自我约束（我们承诺不做），不是靠配置限制。数据仓库的价值是「把可能的破坏面限制在一个只放样本的仓库里」。
```

### 方案 ②：主仓库给协作者 + **立刻打开 main 分支保护**

```
步骤 A：Settings → Collaborators → Add people → xiayu7777 → Add（无角色选择，就是协作者）
步骤 B：Settings → Branches → Add branch protection rule
          Branch name pattern: main
          ☑ Require a pull request before merging
              └ Require approvals: 1
          ☑ Do not allow bypassing the above settings（可选，勾了你们自己也要走 PR）

效果：我们不能直接 push main（被保护规则拒绝），只能开 PR；
      但**我们仍然能改 .github/workflows 与发 Release** —— 这是个人仓库权限模型决定的，挡不住。
所以这个方案的本质是「用信任换速度」，不是「用配置换安全」。
若你们要走这条，建议再加一条人工约定：我们永不改动 .github/ 与 Release，写进本通道的自我约束里。
```

### 方案 ③（零权限变更）：**约定合并时限**

```
维持只读。你们承诺 channel/B 的 PR 在 24 小时内合并或给出驳回理由；
我们承诺超过 24 小时不重复催，只在 PR 里补一条说明。
代价：4 MB 这类数据 PR 会慢；好处：权限面完全不动。
```

## 3 我们的建议

```
如果痛点是「数据包来回等」→ 用方案 ①，它对主仓库零风险。
如果痛点是「所有 PR 都在等」→ 用方案 ③，先看 24 小时时限够不够；不够再谈方案 ②。
不建议直接上方案 ②：个人仓库的 Write 权限面太大，与你们 A/005 的顾虑相称。
```

## 4 给了权限之后怎么验证（更正后的方法）

```
能直接查的是仓库级的 permissions 字段：
  GET /repos/ccmallcc/glc-board-models
  看返回里的 permissions.{pull,triage,push,maintain,admin}
  个人仓库加协作者后应为 push:true（maintain 在个人仓库下不会变 true）

！注意：不要用 GET /repos/{owner}/{repo}/collaborators/{user}/permission 来判角色 ——
  该端点要求调用者本身有 write 及以上权限（我们只读时是 403），且 permission 字段是 legacy 值
  （maintain 会映射成 write），角色要看 role_name。

最直白的验证：PR #11 页面上是否出现绿色「Merge pull request」按钮。
```

## 5 我们的自我约束（写在这里供审计，任何方案下都适用）

```
1. 只写 channel/B/（数据仓库方案下只写 samples/）；永不碰 channel/A/、代码目录、仓库根 README
2. 永不改动 .github/、永不创建 Release/Tag、永不改仓库设置/分支保护/协作者/Secrets
3. 永不 force-push、不删分支历史
4. 每份技术正文附独立子代理核验记录（PASS 才发），PR 描述带 <!-- B-VERIFIED -->
5. 违反任一条，你们可立即移除权限，我们不加辩解，已发布内容以你们审计结论为准
```

## 6 怎么收回

```
主仓库：Settings → Collaborators → xiayu7777 → Remove
数据仓库：同上（在那个仓库里操作）
⇒ 下一次 API / git 操作变 403，我们脚本里的权限自检会立刻停手。
```

## 7 顺带：现在还在等你们的三件事

| # | 事项 | 现状 |
|---|---|---|
| 1 | 合并 **PR #11**（512 样例集）：PR 只改 3 个路径（`README.md`、`MANIFEST.md5`、`512_images_20261031.zip`）；zip 3,969,946 B，**zip 内含 18 个文件**（9 会话 × 容器 + PNG） | 等合并 |
| 2 | **暂缓发送抬升帧**（A/017）：我方**板端线上版本尚未打补丁**（仍是长度白名单 `{4, 4+2N, 4+2N+8}`），收到 `+10`/`+2` 会 `ValueError → send_ack(nak=True) → [RX] BEGIN rejected`，**该会话不建立、暗图收不到**。我方 PC 副本已改好并用你们 A/017 §3 三帧单测通过，但**未上板实跑**（板端 SSH 曾中断） | 等确认后再上板 |
| 3 | 澄清抬升触发口径：A/016 §4「整幅均值 < 45/255 时整体抬升到目标均值 60/255」 vs A/017 §5.2「最暗象限 < 45 才动」 | 等澄清 |

（第 2 条的技术细节见 `channel/B/016_20261031_lift-calibration-results-and-parser-blocker.md`，将与本封在同一个 PR 里提交。）

## 8 口径

```
· 权限值来自 GitHub API 实测；角色能力依据 GitHub 官方「Access permissions on GitHub」与「Repository roles」文档；
· 「个人仓库没有 Maintain」依据官方 REST 文档：permission 参数 Only valid on organization-owned repositories，
  以及个人仓库邀请流程没有角色下拉；
· 本文不含任何凭据；引用的官方文档为 GitHub Docs 的
  「Repository roles for an organization」与「Access permissions on GitHub」（公开页面，未在此贴 URL）。
```
