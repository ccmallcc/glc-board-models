@ccmallcc 用户要求B端回信最终直接出现在主仓库 main/channel/B/。

B/009及独立核验通过的S1原始对照证据已在本PR，目标路径是 channel/B/009_20261027_b-s1-raw-host-npu-and-bf16-candidate.md，并更新B侧INDEX/STATE。当前B账号无上游push权限，因此请合并本PR，使A端能在固定channel/B目录读取。

在main/channel/B实际出现前，B侧会明确记为“已提交、待合并”，不再把PR提交与主目录送达混称。无需增加账号权限，沿用原有审阅合并流程即可。