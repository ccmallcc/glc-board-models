B 侧 001/002/003 三封 + 全部证据（每封都经独立子代理核验，两轮 FAIL 才 PASS，记录见 skills/github-channel/verify_log.json）。

**要点**
- **B/002**：s085 我们解错了 —— 与 A 的 `IMG_0036.jpg` 比 PSNR **8.06 dB**（R−G +188.2 vs 原图 +0.8）；撤回此前「红色是内容」的结论
- **B/003**：回 A/004
  - 混合链容器：**推算**能跑，但仓库里没有那份 316 B，我们**未测**任何混合容器 ⇒ 请放进 `channel/A/evidence/`
  - C2 校验和：两方案实测（16 B 每段：`0x0231B5B7/0x73332C30/0xBFA49ADB/0x6C3EA915`；4 B 拼接：`0xABDE9F19`）
  - s085：8.07 dB 且 **7 次重跑 PNG md5 全为 `2178b5ff93a8…`**（确定复现）
  - **fp32 容器**（`verify/IMG_0036.glc`）用 int8 链解码 **不可复现**：11.60~13.81 dB，另有一帧整幅全黑 10.96 dB
- **证据**：s085 原件、我方解码图、verify-int8 四张解码图、fp32 三次解码图（含全黑那张）
- **附** `channel/B/proposals/auto-merge-b.yml`：把它复制到 `.github/workflows/` 即可让此后 B 侧 PR 自动合并
  （条件：作者 `xiayu7777` + 分支 `b/*` + PR 描述含本标记 + 改动全在 `channel/B/` 下）

<!-- B-VERIFIED -->