# 抽查共享包里的数字是否与实测报告一致
# 用法：powershell -File fact_check.ps1
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$S = 'E:\fudanwei\GLC-共享包'
$R = "$S\附录_实测报告"
$W = 'E:\fudanwei\工作区\reports'

# 每项：共享包里该出现的字符串 -> 应该在哪个报告里找到
$checks = @(
  @{ n='真Kodak q0 bpp';      inPack='0.026493';      inRep='V6_Kodak全量基准与开销拆解报告.md' },
  @{ n='真Kodak q0 PSNR';     inPack='21.322';        inRep='V6_Kodak全量基准与开销拆解报告.md' },
  @{ n='q3 bpp';              inPack='0.039212';      inRep='V6_Kodak全量基准与开销拆解报告.md' },
  @{ n='整包开销 q0';          inPack='+8.95%';        inRep='V6_Kodak全量基准与开销拆解报告.md' },
  @{ n='256² 整包 313B';      inPack='313.0';         inRep='V5_自产容器闭环报告.md' },
  @{ n='CDF 紧凑 27256';      inPack='27,256';        inRep='V2_CDF常量表与scale索引对拍报告.md' },
  @{ n='CDF 占 BRAM 9.38%';   inPack='9.38%';         inRep='V2_CDF常量表与scale索引对拍报告.md' },
  @{ n='填充表 68.99%';       inPack='68.99%';        inRep='V2_CDF常量表与scale索引对拍报告.md' },
  @{ n='scale→index 400048';  inPack='400,048';       inRep='V2_CDF常量表与scale索引对拍报告.md' },
  @{ n='BF16 _ZG +0.27%';     inPack='+0.27%';        inRep='V4_ZG产物数值对拍报告.md' },
  @{ n='INT8 _ZG −0.507';     inPack='−0.507';        inRep='V4_ZG产物数值对拍报告.md' },
  @{ n='INT8 _ZG +0.80%';     inPack='+0.80%';        inRep='V4_ZG产物数值对拍报告.md' },
  @{ n='回归 34/34';          inPack='34/34';         inRep='V3_回归向量集报告.md' },
  @{ n='团队码流 221/224';    inPack='221/224';       inRep='V3_回归向量集报告.md' },
  @{ n='PC 解码 36.7ms';      inPack='36.7';          inRep='V12_V13_PC侧接收与传输协议报告.md' },
  @{ n='PNG 41.9ms';          inPack='41.9';          inRep='V12_V13_PC侧接收与传输协议报告.md' },
  @{ n='LPIPS q0 0.1961';     inPack='0.1961';        inRep='V7_感知指标实测报告.md' },
  @{ n='INT8 ΔLPIPS +0.0088'; inPack='+0.0088';       inRep='V7_感知指标实测报告.md' },
  @{ n='v11 权威表 v11';      inPack='+0.044 dB';     inRep='V4_ZG产物数值对拍报告.md' },
  @{ n='数据集审计存在';       inPack='matplotlib';    inRep='数据集完整性审计报告.md' },
  # ---------- 本轮新增：算子覆盖度 ----------
  @{ n='落点 6,401';          inPack='6,401';         inRep='NPU算子覆盖度产物级审计报告.md' },
  @{ n='落NPU 6,365';         inPack='6,365';         inRep='NPU算子覆盖度产物级审计报告.md' },
  @{ n='NPU 算子 14 种';      inPack='14 种';         inRep='NPU算子覆盖度产物级审计报告.md' },
  @{ n='指令节点 1,188';      inPack='1,188';         inRep='NPU算子覆盖度产物级审计报告.md' },
  @{ n='节点差 529';          inPack='529';           inRep='NPU算子覆盖度产物级审计报告.md' },
  @{ n='零 precheck';         inPack='precheck';      inRep='NPU算子覆盖度产物级审计报告.md' },
  @{ n='parse 落点坑';        inPack='@hostt';        inRep='NPU算子覆盖度产物级审计报告.md' },
  # ---------- 本轮新增：自定义硬算子 ----------
  @{ n='硬算子地址 0x800C';   inPack='0x800C';        inRep='自定义硬算子官方机制调研报告.md' },
  @{ n='官方示例 206 KB';     inPack='206 KB';        inRep='自定义硬算子官方机制调研报告.md' },
  @{ n='官方算子 DetPostZG';  inPack='DetPostZG';     inRep='自定义硬算子官方机制调研报告.md' },
  @{ n='CustomOp 机制';       inPack='CustomOp';      inRep='自定义硬算子官方机制调研报告.md' },
  @{ n='两种动机原文';        inPack='加速 Icraft 算子'; inRep='自定义硬算子官方机制调研报告.md' },
  # ---------- 本轮新增：数字应已登记到 07 ----------
  @{ n='07 已登记 6401';      inPack='6,401';         inRep='../07_数字口径表.md' },
  @{ n='07 已登记 1188';      inPack='1,188';         inRep='../07_数字口径表.md' },
  @{ n='07 已登记 0x800C';    inPack='0x800C';        inRep='../07_数字口径表.md' },
  # ---------- 2026-09-14 新增：赛事身份与赛题事实（权威依据 = 11） ----------
  @{ n='复旦微QQ群 790072144'; inPack='790072144';     inRep='../11_官方赛题原文与评分标准.md' },
  @{ n='赛道官网 fpgachina';   inPack='fpgachina.cn';  inRep='../11_官方赛题原文与评分标准.md' },
  @{ n='报名官网 socchina';    inPack='socchina.net';  inRep='../11_官方赛题原文与评分标准.md' },
  @{ n='报名截止 09-22';       inPack='2026-09-22';    inRep='../11_官方赛题原文与评分标准.md' },
  @{ n='提交截止 11-04';       inPack='2026-11-04';    inRep='../11_官方赛题原文与评分标准.md' },
  @{ n='决赛 11-20';           inPack='2026-11-20';    inRep='../11_官方赛题原文与评分标准.md' },
  @{ n='赛道QQ群 1043037750';  inPack='1043037750';    inRep='../11_官方赛题原文与评分标准.md' },
  @{ n='决赛编程考核';         inPack='FPGA 基础编程'; inRep='../11_官方赛题原文与评分标准.md' },
  @{ n='轻量版13项未焊接';     inPack='PL 端千兆网';  inRep='../11_官方赛题原文与评分标准.md' },
  @{ n='官方可选算子-数据压缩'; inPack='数据压缩';      inRep='../11_官方赛题原文与评分标准.md' },
  @{ n='硬性要求-1项FPGA';     inPack='至少完成 1 项 FPGA'; inRep='../11_官方赛题原文与评分标准.md' },
  @{ n='Procise 赛题原文';     inPack='Procise';       inRep='../11_官方赛题原文与评分标准.md' },
  @{ n='PRJ_VER 0x23120600';   inPack='0x23120600';    inRep='自定义硬算子官方机制调研报告.md' },
  @{ n='赛题指南已下载';       inPack='2026FPGA赛道选题指南'; inRep='../11_官方赛题原文与评分标准.md' },
  # ---------- 2026-09-14 晚：E1（AI 工具使用记录）落地 ----------
  @{ n='E1表已建';            inPack='AI 工具使用记录'; inRep='../12_AI工具使用记录.md' },
  @{ n='E1-贡献边界';          inPack='AI 贡献边界';     inRep='../12_AI工具使用记录.md' },
  @{ n='E1-可复用流程';        inPack='可复用的 AI 辅助开发流程'; inRep='../12_AI工具使用记录.md' },
  @{ n='E1-错误修正案例';      inPack='错误修正';        inRep='../12_AI工具使用记录.md' },
  @{ n='E1-六案例-数据集';     inPack='matplotlib';     inRep='../12_AI工具使用记录.md' },
  @{ n='E1-六案例-parse层级';  inPack='quantize';       inRep='../12_AI工具使用记录.md' },
  @{ n='E1-立场句';            inPack='人负责证伪';      inRep='../12_AI工具使用记录.md' },
  @{ n='报名已完成';           inPack='已确认报名';      inRep='../06_接下来要做什么.md' },
  # ---------- 2026-09-14 晚：Procise 器件命名（GUI 实测 + 手册交叉验证） ----------
  @{ n='器件名 jfmql30tai676h'; inPack='jfmql30tai676h'; inRep='../10_三块芯片的开发链路.md' },
  @{ n='器件名也在 09 术语表';   inPack='jfmql30tai676h'; inRep='../09_资料索引与术语表.md' },
  @{ n='fmql族无30系列';        inPack='没有 fmql30';    inRep='../10_三块芯片的开发链路.md' },
  @{ n='PL库二选一 7z030ai';    inPack='7z030ai';        inRep='../10_三块芯片的开发链路.md' },
  @{ n='Procise 版本 2025.1.1'; inPack='2025.1.1';       inRep='../04_环境安装指南.md' },
  @{ n='五套器件名';            inPack='五套名字';        inRep='../10_三块芯片的开发链路.md' },
  @{ n='烧写层 JFMQL30TAI';     inPack='JFMQL30TAI';     inRep='../09_资料索引与术语表.md' },
  # ---------- 2026-09-14 晚 2：E2 入门练习（管脚表出处核对） ----------
  @{ n='E2练习已建';            inPack='led_counter';    inRep='../E2_FPGA入门练习/README.md' },
  @{ n='LED管脚 PL_LED1=J1';    inPack='J1';             inRep='../E2_FPGA入门练习/README.md' },
  @{ n='PL网口管脚 AD23';       inPack='AD23';           inRep='../E2_FPGA入门练习/README.md' },
  @{ n='PL时钟管脚缺失已记录';   inPack='PL 时钟管脚';     inRep='../E2_FPGA入门练习/README.md' },
  @{ n='PL时钟缺口也在 06-T10'; inPack='PL_100MHz';      inRep='../06_接下来要做什么.md' },
  @{ n='PL时钟缺口已进提问清单'; inPack='PL_100MHz';      inRep='../对外提问清单-复旦微FAE.md' },
  # ---------- 2026-09-14 晚 3：lite vs 完整版差异分析 ----------
  @{ n='lite差异表在11';        inPack='采用同一套 PCB';  inRep='../11_官方赛题原文与评分标准.md' },
  @{ n='lite=接口裁剪版';       inPack='接口裁剪版';       inRep='../11_官方赛题原文与评分标准.md' },
  @{ n='电流监控影响';          inPack='电流监控';         inRep='../11_官方赛题原文与评分标准.md' },
  @{ n='lite对比也在09术语表';  inPack='接口裁剪版';       inRep='../09_资料索引与术语表.md' },
  @{ n='补焊-官方劝阻原文';    inPack='请不要对';         inRep='../11_官方赛题原文与评分标准.md' },
  @{ n='补焊-自研硬件允许';    inPack='设计硬件';         inRep='../11_官方赛题原文与评分标准.md' },
  # ---------- 2026-09-14 晚 4：平台定案 lite ----------
  @{ n='lite定案在11';          inPack='定案（2026-09-14）：本队使用'; inRep='../11_官方赛题原文与评分标准.md' },
  @{ n='码流带宽占比0.046%';    inPack='0.046%';          inRep='../11_官方赛题原文与评分标准.md' },
  @{ n='评分表只要功耗估计';    inPack='功耗估计';         inRep='../11_官方赛题原文与评分标准.md' },
  @{ n='方案早已判定带宽非瓶颈'; inPack='带宽不是卖点也不是瓶颈'; inRep='../11_官方赛题原文与评分标准.md' },
  @{ n='lite定案也在09术语表';  inPack='定案（2026-09-14）：lite 版'; inRep='../09_资料索引与术语表.md' },
  @{ n='lite定案也在01';        inPack='定案 2026-09-14';   inRep='../01_项目背景与目标.md' },
  @{ n='lite定案也在README';    inPack='lite（轻量版悟净）'; inRep='../README.md' },
  # ---------- 2026-09-14 晚 5：GitHub 连通性会抖动（坑 14 更新） ----------
  @{ n='坑14-四时刻实测表';    inPack='同一天内实测到的情况'; inRep='../08_踩过的坑与注意事项.md' },
  @{ n='坑14-端口开不等于能用'; inPack='端口开着 ≠ 能用';  inRep='../08_踩过的坑与注意事项.md' },
  @{ n='README-连通性抖动';     inPack='连通性会抖动';     inRep='../README.md' },
  @{ n='坑14-抖动不是切换';    inPack='几分钟内就能变一次'; inRep='../08_踩过的坑与注意事项.md' },
  @{ n='一键推送脚本已建';     inPack='git_push.ps1';     inRep='../README.md' }
)

$ok = 0; $bad = 0
Write-Host ''
Write-Host '========== 数字出处抽查 =========='
foreach ($c in $checks) {
    $rep = Join-Path $R $c.inRep
    $inRep = if (Test-Path $rep) { (Select-String -Path $rep -Pattern ([regex]::Escape($c.inPack)) -Quiet) } else { $false }
    # 在共享包正文里找（排除附录）
    $inDoc = (Get-ChildItem $S -File -Filter *.md | Select-String -Pattern ([regex]::Escape($c.inPack)) -Quiet)
    $mark = if ($inRep) { '[OK]  ' ; $ok++ } else { '[FAIL]'; $bad++ }
    Write-Host ("  {0} {1,-22} 报告中有={2,-6} 正文引用={3}" -f $mark, $c.n, $inRep, $inDoc)
}
Write-Host ''
Write-Host ("  {0} 项一致 ｜ {1} 项对不上" -f $ok, $bad)
Write-Host ''

# ========== 报告同步检查：工作区\reports 与 附录_实测报告 是否一致 ==========
Write-Host '========== 报告同步检查（工作区 -> 共享包）=========='

# 计算"内容哈希"：先把 CRLF 归一化成 LF 再算 SHA256。
# 为什么需要：.gitattributes 把 *.md 钉成 eol=lf，git 提交/检出时行尾会被改写，
# 而 工作区\reports 下的原稿与共享包里的副本行尾未必一致。
# 实测（2026-09）：27 份报告曾因**纯行尾差异**被误报为"内容不同"。
function Get-ContentHash([string]$Path) {
    $t = [System.IO.File]::ReadAllText($Path)
    $t = $t -replace "`r`n", "`n"
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($t)
        return ([System.BitConverter]::ToString($sha.ComputeHash($bytes)) -replace '-', '')
    } finally { $sha.Dispose() }
}

$drift = 0; $same = 0; $onlyW = 0
if (Test-Path $W) {
    foreach ($f in (Get-ChildItem $W -File -Filter *.md)) {
        $dst = Join-Path $R $f.Name
        if (Test-Path $dst) {
            $h1 = Get-ContentHash $f.FullName
            $h2 = Get-ContentHash $dst
            if ($h1 -eq $h2) { $same++ }
            else { Write-Host ("  [DIFF] {0}  —— 两侧内容不同：请人工判断该往哪边同步（本脚本只比哈希，不比较新旧！）" -f $f.Name); $drift++ }
        } else {
            Write-Host ("  [缺]   {0}  —— 未复制进共享包" -f $f.Name); $onlyW++
        }
    }
}
# 另外几组"工作区 -> 共享包"的显式配对（不在 reports\ 里，单独核对）
$extraPairs = @(
    @{ src = 'E:\fudanwei\工作区\对外提问清单-复旦微FAE.md'; dst = "$S\对外提问清单-复旦微FAE.md" }
)
foreach ($p in $extraPairs) {
    $leaf = Split-Path $p.dst -Leaf
    if ((Test-Path $p.src) -and (Test-Path $p.dst)) {
        $h1 = Get-ContentHash $p.src
        $h2 = Get-ContentHash $p.dst
        if ($h1 -eq $h2) { Write-Host ("  [OK]   {0} 与工作区一致" -f $leaf); $same++ }
        else { Write-Host ("  [DIFF] {0} 与工作区不一致：请人工判断该往哪边同步（本脚本只比哈希，不比较新旧！）" -f $leaf); $drift++ }
    } else {
        Write-Host ("  [缺]   {0} 有一侧不存在" -f $leaf); $onlyW++
    }
}Write-Host ("  一致 {0} 份 ｜ 内容不同 {1} 份 ｜ 未复制 {2} 份" -f $same, $drift, $onlyW)
Write-Host ''

# ========== 交叉引用检查：正文里提到的 .md 是否真的存在 ==========
Write-Host '========== 交叉引用检查 =========='
$mdFiles = @(Get-ChildItem $S -Recurse -File -Filter *.md)
$allNames = @{}; foreach ($m in $mdFiles) { $allNames[$m.Name] = $true }
# 工作区里的文档也算"存在" —— 09 有一节专门列工作区文档（那些文件不在共享包里）
$wsNames = @{}
$wsRoot = 'E:\fudanwei\工作区'
if (Test-Path $wsRoot) {
    foreach ($m in (Get-ChildItem $wsRoot -File -Filter *.md -ErrorAction SilentlyContinue)) { $wsNames[$m.Name] = $true }
}
# 外部文件白名单：这些 .md 既不在共享包里，也不在工作区里，
# 而是**官方 demo 包 / 官方资料**自带的文档。正文引用它们是正确的，不该报"找不到"。
$extNames = @{
    'BUILD_GUIDE.md'   = '官方 demo 包 docs/BUILD_GUIDE.md'
    'API_REFERENCE.md' = '官方 demo 包 docs/API_REFERENCE.md'
    '说明.md'          = 'E:\fudanwei\开发板传输包\说明.md（打包给板子旁边用的自包含说明，仓库之外）'
}
$missing = @(); $okRef = 0; $skipEllipsis = 0
foreach ($doc in (Get-ChildItem $S -File -Filter *.md)) {
    $txt = Get-Content $doc.FullName -Raw -Encoding UTF8
    # 反引号里的完整 .md 文件名
    foreach ($m in [regex]::Matches($txt, '`([^`\r\n]{2,80}?\.md)`')) {
        $raw = $m.Groups[1].Value
        if ($raw -match '\.\.\.') { $skipEllipsis++; continue }   # 省略写法（如 V2_...报告.md），不校验
        if ($raw -match '\*')     { $skipEllipsis++; continue }   # 通配写法（如 _layerwise_s1_*.md），不校验
        $name = Split-Path $raw -Leaf
        if ($allNames.ContainsKey($name) -or $wsNames.ContainsKey($name) -or $extNames.ContainsKey($name)) { $okRef++ }
        else { $missing += ("{0} -> {1}" -f $doc.Name, $name) }
    }
    # 反引号里的两位编号（如 `06`、`09`）
    foreach ($m in [regex]::Matches($txt, '`(0[0-9])`')) {
        $pre = $m.Groups[1].Value + '_'
        if ($mdFiles | Where-Object { $_.Name.StartsWith($pre) }) { $okRef++ }
        else { $missing += ("{0} -> {1}" -f $doc.Name, $m.Groups[1].Value) }
    }
}
if ($missing.Count -eq 0) {
    Write-Host ("  [OK] 正文引用的 {0} 处文档全部存在（另有 {1} 处省略写法未校验）" -f $okRef, $skipEllipsis)
} else {
    Write-Host ("  [X] 有 {0} 处引用找不到对应文件：" -f $missing.Count)
    $missing | Select-Object -Unique | ForEach-Object { Write-Host ("      {0}" -f $_) }
}
Write-Host ''
# 反向检查：作废数字不应作为"当前值"出现在 07 之外
Write-Host '========== 作废数字检查 =========='
$stale = @('0.01965','161 字节','44 字节头','+56.7%')
# 注意：PowerShell 变量名大小写不敏感 —— 这里绝不能用 $s 作循环变量，
# 它会把上面的 $S（文件夹路径）覆盖掉。我们实际踩过这个坑。
$topMd = @(Get-ChildItem $S -File -Filter *.md)
foreach ($pat in $stale) {
    $hits = @($topMd | Select-String -Pattern ([regex]::Escape($pat)))
    $where = ($hits | ForEach-Object { $_.Filename } | Sort-Object -Unique) -join ', '
    Write-Host ("  {0,-12} 出现在: {1}" -f $pat, $(if($where){$where}else{'(无)'}))
}
Write-Host ''
Write-Host '  说明：作废数字只应出现在「更正说明」里 ——'
Write-Host '        07（作废清单）是主要位置；03/08 在讲"这里曾经写错过"时也会提到。'
Write-Host '        判断标准：它必须紧邻"正确值"或"已作废"字样，不能单独出现。'
Write-Host ''

# ========== 赛事身份一致性检查（2026-09-14 新增） ==========
# 背景：本项目文档一度把赛事写成"集创赛"（实际是"嵌赛"），
#       并且引用过一个不存在的"钉钉群"。这两样只允许作为**更正说明**出现。
Write-Host '========== 赛事身份一致性检查 =========='
$wrongEvent = @('集创赛', 'ciciec', '130085038764', '钉钉群')
$correctMark = @('嵌赛', '不是', '已作废', '更正', '另外一个比赛', '另一个比赛', '错误比赛', '已删除')
$evtBad = 0; $evtOk = 0
foreach ($doc in $topMd) {
    $txt = Get-Content $doc.FullName -Raw -Encoding UTF8
    foreach ($w in $wrongEvent) {
        if ($txt -notlike "*$w*") { continue }
        # 命中错词时，同一文件里必须同时出现"更正/不是/嵌赛"之类的语境词
        $hasCtx = $false
        foreach ($c in $correctMark) { if ($txt -like "*$c*") { $hasCtx = $true; break } }
        if ($hasCtx) { $evtOk++ }
        else {
            Write-Host ("  [X] {0} 提到「{1}」但没有更正语境 —— 疑似残留错误信息" -f $doc.Name, $w)
            $evtBad++
        }
    }
}
if ($evtBad -eq 0) {
    Write-Host ("  [OK] 错词（集创赛/ciciec/钉钉群/130085038764）出现 {0} 处，全部带更正语境" -f $evtOk)
} else {
    Write-Host ("  [X] {0} 处错词缺少更正语境" -f $evtBad)
}
# 正确赛事标识必须存在
foreach ($must in @('嵌赛', 'fpgachina.cn', '790072144', 'www.socchina.net')) {
    $any = $false
    foreach ($doc in $topMd) { if ((Get-Content $doc.FullName -Raw -Encoding UTF8) -like "*$must*") { $any = $true; break } }
    Write-Host ("  {0} 正确赛事标识「{1}」{2}" -f $(if($any){'[OK]  '}else{'[X]   '}), $must, $(if($any){'已写入正文'}else{'**缺失**'}))
}
Write-Host ''