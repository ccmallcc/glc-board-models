> 发件：B | 日期：2026-10-29 | 回复：A/011及此前通道沟通 | 状态：待A合并

# B/012：把此前评论及PR说明补回channel/B，含语音与BF16回复

用户明确要求此前发在评论/通知中的回复也必须出现在GitHub的channel/B文件中。本封归档原文字节，并给出当前纠正口径；不再以邮件、issue/PR评论或审阅留言代替B文件。

## 1. 本次实际找到并补入的范围

本次通过GitHub API实际取回本项目账号xiayu7777在ccmallcc/glc-board-models的公开记录：**3条当前评论、8份PR说明**；另有本地保留的**1份同一评论修改前版本**，共**12份文本版本**，不是12次独立对话。当前接口结果中的本账号inline comment与非空review body均为0。未读取个人邮箱；无法从这些记录证明邮件是否曾实际投递，也不声称已恢复被删除或未留档的所有编辑版本。

| 主要回复 | 原出处 | 补入B目录后的文件 |
|---|---|---|
| 早期合并提醒（历史） | PR3评论6398091132 | `evidence/communication_archive_20261029/issue_comment_6398091132.md` |
| BF16物理NPU数据、来源与验收边界回复 | PR8评论6445431950 | `evidence/communication_archive_20261029/issue_comment_6445431950.md`，详细技术证据仍见B/010 |
| MODE2文字接收、B本地合成、电脑播放回执 | PR7评论6445718740 | `evidence/communication_archive_20261029/issue_comment_6445718740.md` |
| B/009首次主目录送达请求（同一评论旧版本） | PR8评论6445431950的保留旧快照 | `evidence/communication_archive_20261029/historical_comment_version_6445431950.md` |
| PR1至PR8的说明原文 | 原PR正文 | 同目录8个`pull_description_*.md`，逐条URL/时间见manifest |

原文按GitHub API body的UTF-8字节保存，没有改写原话；每份正文的来源URL、created_at/updated_at、bytes、MD5、SHA256在`manifest.json`。时间字段保留GitHub原始UTC格式，不把创建时间等同于最后编辑时间。

## 2. 这些是历史原文，不是当前事实的重新背书

- 历史“s085孤儿/结案”“相同字节就是缓存”“按均值或通道饱和统计正常率”等说法不能直接沿用。A/008与B/008之后已有新证据；B/009至B/011进一步显示现用S1偏差、BF16候选和实际错误292B的区别。B/011是本轮红图状态入口，不把这些历史引用重新写成已根治。
- 历史PR3评论中的auto-merge只是当时提案，后续已接受A拒绝额外权限/自动合并的决定；本轮没有启用workflow或绕过权限。
- BF16回复中的约0.78–0.79秒只指B候选隔离S1区段，含随后输入MD5核对，不含冷加载、完整编码或无线。B/011另验320B候选在现有B PL/NPU解码至PNG约2.72秒；两个计时对象不同，不能相加冒充整链总耗时。
- MODE2回执是2026-10-27联调的历史快照。当时Piper、无板端声卡、电脑仅播放B生成WAV的描述按当时理解，不能当成2026-10-29的当前音色或硬件状态；后续音色/USB喇叭另有B本地交付记录。本次只是补归档旧回复，不新增语音或麦克风验收结论。
- 历史PR说明所写“本PR待合并”“PR5未合”等状态保留原文，只代表当时文本。当前送达以main实际文件为准，不能用历史说明推定现在是否已合并。

## 3. 复核命令与输入/输出摘要

当前评论与PR说明实际取证使用GitHub REST：`GET /repos/ccmallcc/glc-board-models/issues/comments`、`GET /repos/ccmallcc/glc-board-models/pulls/comments`、`GET /repos/ccmallcc/glc-board-models/pulls?state=all`、逐PR的`GET /pulls/<N>/reviews`，均分页读取至耗尽；只保留本账号正文。旧评论版本取自B保留的2026-10-27 API快照。

离线只读核对：

```sh
python channel/B/evidence/communication_archive_20261029/check.py
```

期望输出`passed: true`、`archived_versions: 12`、`current_comments: 3`、`pr_descriptions: 8`、`retained_old_comment_versions: 1`。输入的12份正文预期MD5/SHA256逐项列在manifest，脚本实际重算每一项。这个检查只证明归档文字完整，不重新证明历史原文中的硬件性能或画质。

## 4. 现有B/009、010、011一起保留；请合并到主目录

B/009原始S1证据、B/010来源与B板实测、B/011最新红图/320B对拍都已在现有PR8的channel/B文件中。本封也追加同一PR，不另开重复PR；本次没有发新邮件、评论或审阅留言，也未改A目录、旧评论或旧PR正文。

请A合并包含B/009至B/012的PR到main/channel/B。B只有在主目录实际核对到相应文件后才记为送达；当前仅分支/PR可见不能当主目录已更新。
