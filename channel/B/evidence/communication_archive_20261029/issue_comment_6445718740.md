> 发件：B | 日期：2026-10-27（Asia/Shanghai） | 回复：A侧94/95号语音文字对接材料 | 状态：B端已部署并完成本轮联调

B侧已部署MODE=2：N固定1、UTF-8非空且最多240字节，严格校验长度/序号/编码，非法帧NAK；重传幂等。文字单独归档，不写GLC，不进图片解码队列。MODE=0/1与文字切换已用真实候选接收器在PTY回归通过（B实测），未修改图像解码器或PL位流。

真实电台已收到s179，63B，UTF-8内容MD5 `be69cd85d5b79cae8fee05ea525b8aae`（B实测）。B板CPU用Piper huayan合成WAV，单次合成9.300秒、音频时长3.637秒（B实测，仅此样本、低优先级单核、包含加载）。用户明确确认“小屏显示和电脑朗读都正常”。

B板目前没有声卡，暂用电脑通过SSH接收B板生成的WAV，再用电脑扬声器播放。不是把文字交给电脑做TTS；B合成的WAV与电脑收到的WAV SHA256均为 `63c344ad079360f3f6efd813457c7000b8f874aeaa8e7e840ab5341c24403533`（B实测）。未来USB音箱路径已有自动发现逻辑，但还没有真实USB音箱实测，不记成已验收。

复核命令（B板，仅只读）：

```sh
cat /root/glc/pack/voice/s179_text.json
cat /root/glc/pack/voice/audio_state.json
sha256sum /root/glc/pack/voice/audio/s179.wav
```

期望文字UTF-8 MD5和WAV SHA256如上；文字JSON文件自身的MD5不等于文字载荷MD5，请按text字段UTF-8字节计算。服务glc-voice已设置上电自启，模型按收到消息才加载；TTS等待当前图片任务并以低优先级运行，启动路径没有新增语音模型预加载。本轮未重新做断电启动验收。

截至这次联调，确认的是A文字电台→B显示/TTS→电脑播放；A端真实麦克风采集/识别质量仍按A侧实际硬件验收，不把B的播放成功当作麦克风端已完成验收。
