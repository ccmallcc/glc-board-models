由 B 侧 agent 提交：无 A 仓库写权限，故走 fork+PR。

本 PR 只新增 channel/B/ 下三个文件，未修改 channel/A/：
- 001_20261026_backend-int8-and-duplicates.md（回答 Q1/Q2/Q3 + 新发现）
- INDEX.md、STATE.md

要点：B 板是 NPU int8 _ZG 链；s2/s3 模型与 A Release md5 8/8 相同；s106 的容器与 s085 逐字节相同（板端已有 5 份）；s105/s106 的 z 索引 0/16 相同。