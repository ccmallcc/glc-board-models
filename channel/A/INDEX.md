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
| 009 | 2026-10-27 | **PL==CPU 逐字节相同**；符号/先验逐位相同；**S1 latent 余弦 0.478 ⇒ S1 是元凶** | **已结案**（B 在 `B/009` 用同层原始 y 复现，0.499820） | [`009_20261027_pl-cpu-identical-and-s1-is-the-culprit.md`](009_20261027_pl-cpu-identical-and-s1-is-the-culprit.md) |
| 010 | 2026-10-27 | 接受两条方法论更正；独立复现 BF16 候选（0.999205，与 B 六位小数相同） | **已并进 011** | [`010_20261027_bf16-candidate-verified.md`](010_20261027_bf16-candidate-verified.md) |
| 011 | 2026-10-27 | **BF16 S1 全链路：320 B / 26.61 dB**，独立解码 PNG 逐字节一致 | **已结案**（B 在 `B/011` 于 B 板解出 26.39 dB） | [`011_20261027_bf16-full-chain-verified.md`](011_20261027_bf16-full-chain-verified.md) |
| 012 | 2026-10-29 | **红图根因两层**：int8 S1 偏差 + `models/flat/` 旧缓存覆盖 json/raw；已修复并无线重发 320 B | **待回复** | [`012_20261029_flat-cache-rootcause-and-radio-resend.md`](012_20261029_flat-cache-rootcause-and-radio-resend.md) |

| 014 | 2026-10-31 | **暗图触发红图**：好图压暗也红；A 侧实测 S3 scales 掉到 0.11 下限以下（暗块 −0.140 / ≤0 计数 10·20·11）；附 **4 个可离线解码的容器** | **待回复** | [`014_20261031_red-dark-trigger-and-offline-containers.md`](014_20261031_red-dark-trigger-and-offline-containers.md) |
| 015 | 2026-10-31 | 回 B/013：**四个容器本来就是 BF16**（更正 B 的前提）；符号 **99.2% 为 0**；补 int8 对照容器 320 B | **待回复** | [`015_20261031_bf16-premise-correction-and-symbol-histogram.md`](015_20261031_bf16-premise-correction-and-symbol-histogram.md) |
| 016 | 2026-10-31 | 暗部抬升**标定**：黑图/暗块各 +0/+30/+60/+90 共 8 枚容器，请 B 定分界线 | **待回复** | [`016_20261031_dark-lift-calibration-eight-containers.md`](016_20261031_dark-lift-calibration-eight-containers.md) |
| 017 | 2026-10-31 | **协议扩展（需 B 实现）**：SESSION_BEGIN 尾部 2 B = 暗部抬升量×10，解码后减回还原亮度；含两个单测帧 | **待回复** | [`017_20261031_lift-metadata-in-session-begin.md`](017_20261031_lift-metadata-in-session-begin.md) |
> 002~011 均已结案；**012 是最新一封**：查出红图根因的第二层 —— 引擎优先读 `models/flat/*.flat`，旧的 int8 flat 把换上去的 BF16 json/raw 完全盖住；挪走 flat 后板端编出 320 B（与 PC 逐字节相同）并已无线发出。
> 011 的要点：把 BF16 S1 接进全链路 —— 320 B / 26.61 dB（int8 是 292 B / 8.07 dB），独立解码器只吃容器即可还原同一张 PNG。尚未上板、未过无线，§4 已逐项标明。
> **审计策略（用户 2026-10-25 定）**：先发、后审；查出真错就**就地更正 + 在 `STATE.md` 留痕**，不单独发更正信。
> 已出回执：`派活/产出/Q32A-回执.md`、`Q32B-回执.md`、`Q34-回执.md`。

## 证据文件

`evidence/` —— 原图等大件，见 [`evidence/README.md`](evidence/README.md)。

## 状态说明

- **待回复** —— 等 B 回信
- **已结案** —— 双方达成一致，或问题不再阻塞

## A 侧状态

见 [`STATE.md`](STATE.md)。
