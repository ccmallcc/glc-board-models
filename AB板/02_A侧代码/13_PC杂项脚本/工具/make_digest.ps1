#requires -Version 5.1
<#
    make_digest.ps1 -- 把两份"大手册"压缩成小摘要，喂给 Qoder 而不是喂原文。

    背景（2026-09-18，用户指出）：Qwen3.8-Flash 是小模型，上下文一长注意力就漂移。
    所以**不能让它去读 411 KB / 183 KB 的原文**，得由我们这边先压缩。

    但压缩前先看清楚这两份是什么：
      * Procise原语手册  = 257 个原语的**目录式**手册（每个原语都是"介绍/端口/设计输入/
                           VHDL模板/Verilog模板"五段式），411 KB / 15224 行。
                          → 我们要的不是全文，是**索引**：哪个原语在哪一行。
      * Procise HRDT用户手册 = **抗辐照加固**工具（EDIF 网表 TMR 加固、BRAM/DRAM IP 加固、
                           在轨翻转率预估），183 KB / 3497 行。
                          → **与本队赛题无关**，只需要"这是什么 + 要不要用"。

    产出：
      _digest\原语手册-原语索引.md     （411 KB → 约 12 KB）
      _digest\HRDT-目录与摘要.md       （183 KB → 约 6 KB）
#>
[CmdletBinding()]
param([string]$Docs = 'E:\fudanwei\_logs\procise_docs')

$ErrorActionPreference = 'Stop'
$utf8 = New-Object Text.UTF8Encoding($true)      # 带 BOM 写
$read = New-Object Text.UTF8Encoding($false)

$digestDir = Join-Path $Docs '_digest'
if (-not (Test-Path $digestDir)) { New-Item -ItemType Directory -Path $digestDir -Force | Out-Null }

# ─────────────────────────────────────────────────────────────
# 1) 原语手册 -> 原语索引
# ─────────────────────────────────────────────────────────────
$src = Join-Path $Docs 'Procise原语手册.txt'
$L = [IO.File]::ReadAllLines($src, $read)

$toc  = @{}   # 编号 -> @(名字, 目录行号)
$body = @{}   # 编号 -> 正文起始行号（用 PDF 的 "N / 257" 页标记定位）

for ($i = 0; $i -lt $L.Count; $i++) {
    $t = $L[$i].Trim()

    if ($t -match '^([0-9]{1,3})\.\s*([A-Z][A-Z0-9_]{1,40})\s*\.*\s*$') {
        $n = [int]$Matches[1]
        if (-not $toc.ContainsKey($n)) { $toc[$n] = @($Matches[2], $i + 1) }
        continue
    }
    if ($t -match '^([0-9]{1,3})\s*/\s*257$') {
        $n = [int]$Matches[1]
        if (-not $body.ContainsKey($n)) { $body[$n] = $i + 1 }
    }
}

$sb = New-Object Text.StringBuilder
[void]$sb.AppendLine('# Procise 原语手册 —— 原语索引')
[void]$sb.AppendLine()
[void]$sb.AppendLine('> **本文件由本地脚本自动生成，不是 Qoder 写的，也不是手册原文。**')
[void]$sb.AppendLine('> 生成脚本：`工具\make_digest.ps1`')
[void]$sb.AppendLine()
[void]$sb.AppendLine('| 项 | 值 |')
[void]$sb.AppendLine('|---|---|')
[void]$sb.AppendLine('| 来源 | `E:\fudanwei\_logs\procise_docs\Procise原语手册.txt` |')
[void]$sb.AppendLine('| 原文体量 | 411 KB / 15224 行 / **共 257 页**；手册目录列出的原语编号 **1~57** |')
[void]$sb.AppendLine('| ⚠️ `N / 257` 是什么 | **是页码（第 N 页 / 共 257 页），不是原语编号**。⚠️ 曾误写成「257 个原语」，2026-09-18 由 Q1a 批次发现并纠正 |
| 提取方法 | 原语名：正则 `^<编号>. <原语名>` 取首次出现；页码行：正则 `^<页码> / 257` |')
[void]$sb.AppendLine(('| ⚠️ 提取完整度 | **原语名只自动提到 {0} / 257 个**（其余标题格式不同，正则没抓到）；页码行 257/257 |' -f $toc.Count, $body.Count))
[void]$sb.AppendLine()
[void]$sb.AppendLine('**每个原语在正文里都是同一套五段式**：`N.1 介绍` / `N.2 端口描述` / `N.3 设计输入方法` /')
[void]$sb.AppendLine('`N.4 VHDL 例化模板` / `N.5 Verilog 例化模板`（少数原语没有 `N.2 端口描述`，有 `逻辑真值表` / `可配置属性`）。')
[void]$sb.AppendLine()
[void]$sb.AppendLine('| 编号 | 原语名 | 目录行 | 第 N 页起始行 |')
[void]$sb.AppendLine('|---:|---|---:|---:|')

foreach ($k in ($toc.Keys | Sort-Object)) {
    $b = if ($body.ContainsKey($k)) { 'L' + $body[$k] } else { '—' }
    [void]$sb.AppendLine(('| {0} | `{1}` | L{2} | {3} |' -f $k, $toc[$k][0], $toc[$k][1], $b))
}

[void]$sb.AppendLine()
[void]$sb.AppendLine('## 本队可能要用的几类（按名字粗筛，**未核实**）')
[void]$sb.AppendLine()
[void]$sb.AppendLine('> ⚠️ 这张表是**按原语名字字符串匹配**得到的候选，**没有读正文核实过**。')
[void]$sb.AppendLine('> 要用哪一条，必须回原文对应行号确认。')
[void]$sb.AppendLine()
$want = @{
    'RAM/FIFO 类'   = 'RAM|FIFO|ROM'
    '移位/寄存类'   = 'SHIFT|REG|SRL|DELAY'
    '计数/算术类'   = 'COUNT|ADD|SUB|MULT|ACC|CARRY'
    '比较/逻辑类'   = 'COMP|LUT|AND|OR|NOT|MUX'
    '时钟资源类'    = 'BUFG|BUFR|MMCM|PLL|BUFH|BUFIO|CLK'
    '复位/使能类'   = 'RESET|RST|EN|GLOBAL'
}
foreach ($cat in ($want.Keys | Sort-Object)) {
    $hit = @()
    foreach ($k in ($toc.Keys | Sort-Object)) {
        if ($toc[$k][0] -match $want[$cat]) { $hit += ('{0}(L{1})' -f $toc[$k][0], $toc[$k][1]) }
    }
    [void]$sb.AppendLine(('**{0}**（{1} 条）：{2}' -f $cat, $hit.Count, (($hit | Select-Object -First 40) -join '、')))
    [void]$sb.AppendLine()
}

$outA = Join-Path $digestDir '原语手册-原语索引.md'
[IO.File]::WriteAllText($outA, $sb.ToString(), $utf8)

# ─────────────────────────────────────────────────────────────
# 2) HRDT 手册 -> 目录 + 摘要
# ─────────────────────────────────────────────────────────────
$src2 = Join-Path $Docs 'Procise HRDT用户手册.txt'
$L2 = [IO.File]::ReadAllLines($src2, $read)

$heads = @()
for ($i = 0; $i -lt $L2.Count; $i++) {
    $t = $L2[$i].Trim()
    if ($t -match '^[0-9]+(\.[0-9]+)*\s+\S' -or $t -match '^附录') {
        $clean = ($t -replace '\.{3,}.*$', '').Trim()      # 去掉点线
        if ($clean.Length -ge 3) { $heads += ('L{0}: {1}' -f ($i + 1), $clean) }
    }
}

$sb2 = New-Object Text.StringBuilder
[void]$sb2.AppendLine('# Procise HRDT 用户手册 —— 目录与摘要')
[void]$sb2.AppendLine()
[void]$sb2.AppendLine('> **本文件由本地脚本自动生成**（`工具\make_digest.ps1`），不是 Qoder 写的。')
[void]$sb2.AppendLine()
[void]$sb2.AppendLine('| 项 | 值 |')
[void]$sb2.AppendLine('|---|---|')
[void]$sb2.AppendLine('| 来源 | `E:\fudanwei\_logs\procise_docs\Procise HRDT用户手册.txt` |')
[void]$sb2.AppendLine(('| 原文体量 | 183 KB / {0} 行 |' -f $L2.Count))
[void]$sb2.AppendLine('| 提取方法 | 正则匹配 `^<数字>(.<数字>)* <标题>`，去掉点线 |')
[void]$sb2.AppendLine(('| 提取到标题 | {0} 条 |' -f $heads.Count))
[void]$sb2.AppendLine()
[void]$sb2.AppendLine('## 一、原文开头（前 40 行，原样）')
[void]$sb2.AppendLine()
[void]$sb2.AppendLine('```')
foreach ($i in 0..([Math]::Min(39, $L2.Count - 1))) { [void]$sb2.AppendLine($L2[$i]) }
[void]$sb2.AppendLine('```')
[void]$sb2.AppendLine()
[void]$sb2.AppendLine('## 二、全部标题（含行号）')
[void]$sb2.AppendLine()
foreach ($h in $heads) { [void]$sb2.AppendLine('- ' + $h) }

$outB = Join-Path $digestDir 'HRDT-目录与摘要.md'
[IO.File]::WriteAllText($outB, $sb2.ToString(), $utf8)

# ─────────────────────────────────────────────────────────────
"原语索引 : {0}  ({1:N0} KB -> {2:N0} KB)" -f (Split-Path $outA -Leaf), ((Get-Item $src).Length/1KB), ((Get-Item $outA).Length/1KB)
"HRDT摘要 : {0}  ({1:N0} KB -> {2:N0} KB)" -f (Split-Path $outB -Leaf), ((Get-Item $src2).Length/1KB), ((Get-Item $outB).Length/1KB)
"目录名提取 : {0} / 257" -f $toc.Count
"正文位置   : {0} / 257" -f $body.Count
"HRDT 标题  : {0} 条" -f $heads.Count
