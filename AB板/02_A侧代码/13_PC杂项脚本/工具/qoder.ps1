#requires -Version 5.1
<#
    qoder.ps1 —— 把「派活」目录下的任务书一键派给 Qoder CLI（无人值守）

    用法：
      powershell -File 工具\qoder.ps1 -Status
      powershell -File 工具\qoder.ps1 -Login                # 首次必须人工登录一次
      powershell -File 工具\qoder.ps1 -Task 'Q1a_手册地图与章节索引.md'
      powershell -File 工具\qoder.ps1 -Task 'Q2b_修tb直到仿真过.md' -PermissionMode bypass_permissions
      powershell -File 工具\qoder.ps1 -Task 'X.md' -DryRun
      powershell -File 工具\qoder.ps1 -ListModels

    ── 四条硬约束（都是踩过坑才加的，别删）──────────────────────────────
    1. **额外目录必须 -AddDir 授权**。Qoder CLI 只能读写 --cwd 内的文件，工作区外
       一读就返回 "Allow reading ...?"，无人值守下自动拒绝。（Q1 第一次空跑在这）
    2. **默认模型 Qwen3.8-Flash 是小模型**，上下文一长注意力就漂移、会开始编。
       所以：一次只给它一份小输入；单批输入体量超 -MaxInputKB 直接拒派（除非 -Force）。
       2026-09-18 用户明确要求：**不许让它在超过 ~50% 上下文里干活**。
    3. **必须有真超时**。它可能卡住或长程硬撑，超时即 Kill 并如实记进日志。
       小任务正常几分钟就完；跑 15 分钟以上基本就是在漂移。
    4. **每次派活都是全新会话**（--no-session-persistence）。不续用上一次的上下文——
       这本身就是"上下文长了新建对话"的落地方式。

    ⚠️ 改完本文件后必须跑 `工具\check_ps1.ps1`：
       编辑工具会吃掉 UTF-8 BOM，PowerShell 5.1 就会把中文脚本按 ANSI 读而直接解析失败
       （2026-09-18 已经因此废掉两次派活）。check_ps1.ps1 会报 MISSING-BOM。

    实现说明：
      * prompt 先落盘成 .prompt.txt，再用 Start-Job 里的 node 读文件执行。
        —— 不能把 prompt 当参数传给 Start-Job：它会吃掉参数里的引号，导致 node 语法错。
      * 日志：<任务名>_<时间戳>.log（含模型/退出码/耗时/是否超时/输出末尾）。
#>
[CmdletBinding()]
param(
    [string[]]$Task,
    [switch]$Login,
    [switch]$Status,
    [switch]$ListModels,
    [switch]$DryRun,
    [switch]$Force,                       # 忽略 -MaxInputKB 守卫
    [string]$Root = 'E:\fudanwei\GLC-共享包',
    # Qoder CLI 只能读写工作区（--cwd）内的文件。工作区外的目录必须用 --add-dir 显式授权，
    # 否则任何读取都会返回 "Allow reading ...?" 并在无人值守下被自动拒绝（Q1 第一次就是这么卡的）。
    [string[]]$AddDir = @('E:\fudanwei\_logs', 'E:\fudanwei\工作区'),
    [string]$Model = 'Qwen3.8-Flash',     # 2026-09 期间免费；换模型用 -Model，列全部模型用 -ListModels

    # ── 2026-10-18 新增：CLI 的这几档参数原来没透传，导致"想让它想深一点"做不到 ──
    [string]$Thinking = '',               # auto | adaptive | enabled | disabled
    [string]$ReasoningEffort = '',        # 思考强度（取值按模型支持，如 low/medium/high）
    [int]$ThinkingBudget = 0,             # 固定思考 token 预算（隐含 --thinking enabled）
    [int]$ContextWindow = 0,              # 显式上下文窗口（只对支持的模型有效）
    [int]$MaxOutputTokens = 0,            # 输出上限
    [string]$AllowedTools = '',           # 逗号分隔，如 'WebFetch,WebSearch'
    [switch]$AllowWeb,                    # 便捷开关：放行联网工具（会把权限模式切到 bypass_permissions）
    [string]$Skill = '',                  # 技能目录（含 SKILL.md）；缺省用仓库的 glc-audit
    [switch]$NoSkill,                     # 明确不要技能
    [string]$McpConfig = '',              # MCP 配置（JSON 文件或内联 JSON）→ --mcp-config
    [ValidateSet('default','accept_edits','bypass_permissions','dont_ask','auto')]
    [string]$PermissionMode = 'accept_edits',
    [int]$MaxInputKB = 60,                # 单批输入体量上限（小模型尺度）
    [int]$TimeoutSec = 900                # 真超时：默认 15 分钟
)

$ErrorActionPreference = 'Stop'
# Qoder 的输出是 UTF-8，但 PowerShell 控制台默认按本地代码页解码，中文会变乱码。
# 日志文件本身是对的（显式 UTF-8 写入），这里只为让控制台也看得懂。
try { [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false) } catch { }

function Find-QoderCli {
    $base = Join-Path $env:LOCALAPPDATA 'QoderCli'
    if (-not (Test-Path $base)) { throw "找不到 $base —— Qoder CLI 没装？" }
    $rt = Get-ChildItem $base -Directory -Filter 'gemini-runtime-*' -ErrorAction SilentlyContinue |
          Sort-Object Name -Descending | Select-Object -First 1
    if (-not $rt) { throw "在 $base 下找不到 gemini-runtime-* 目录" }
    $cli = Join-Path $rt.FullName 'qodercli.mjs'
    if (-not (Test-Path $cli)) { throw "找不到 $cli" }
    return $cli
}

function Get-NodeExe {
    $n = Get-Command node -ErrorAction SilentlyContinue
    if ($n) { return $n.Source }
    throw "PATH 里没有 node"
}

# 从任务书里把 `` `文件名.ext` `` 形式的输入挑出来，按候选根目录解析并求体量。
function Measure-DeclaredInput {
    param([string]$Text, [string[]]$Roots)
    $names = [regex]::Matches($Text, '`([^`\r\n]+\.(?:txt|md|v|sv|json|py|csv|sh))`') |
             ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
    $total = 0; $rows = @()
    foreach ($n in $names) {
        foreach ($r in $Roots) {
            if (-not $r) { continue }
            # 任务书里通常写裸文件名（如 `Procise约束手册.txt`），而文件在子目录下
            # （_logs\procise_docs\），所以直接 Join-Path 找不到时要递归找一次。
            $hit = $null
            $cand = Join-Path $r $n
            if (Test-Path $cand -PathType Leaf) {
                $hit = Get-Item $cand
            } else {
                $hit = Get-ChildItem $r -Recurse -File -Filter $n -ErrorAction SilentlyContinue |
                       Select-Object -First 1
            }
            if ($hit) {
                $total += $hit.Length
                $rows += [pscustomobject]@{ File = $n; KB = [math]::Round($hit.Length / 1KB, 1) }
                break
            }
        }
    }
    return [pscustomobject]@{ TotalKB = [math]::Round($total / 1KB, 1); Rows = $rows }
}

$cli  = Find-QoderCli
$node = Get-NodeExe
Write-Host "[qoder] cli   = $cli"   -ForegroundColor DarkGray
Write-Host "[qoder] node  = $node"  -ForegroundColor DarkGray
Write-Host "[qoder] model = $Model" -ForegroundColor DarkGray

if ($Status)     { & $node $cli status 2>&1 | Write-Host; exit $LASTEXITCODE }
if ($ListModels) { & $node $cli --list-models 2>&1 | Write-Host; exit $LASTEXITCODE }

# ── 把"思考/上下文/工具/联网"翻译成 CLI 参数 ────────────────────────────
# ── 技能：CLI 只把技能名+描述注入上下文，**正文不会自动读**（实测 2026-10-18）。
#    所以这里把"先完整读这个文件"写进 prompt 开头，才算真加载。
$skillPath = ''
if (-not $NoSkill) {
    if ($Skill) { $skillPath = $Skill }
    else { $skillPath = Join-Path $Root '工具\qoder技能\glc-audit' }
    $skillMd = Join-Path $skillPath 'SKILL.md'
    if (-not (Test-Path $skillMd)) { $skillPath = '' }
}

$extra = @()
if ($Thinking -eq 'enabled' -and $ThinkingBudget -le 0) {
    # 实测（2026-10-18）：`--thinking enabled` 单独传会让 CLI 直接抛
    #   Error: --thinking enabled requires --thinking-budget <tokens>.
    # 崩掉之后的假象是"所有工具都被权限层拒绝"（Q7 第一次就是这么翻的）。
    $ThinkingBudget = 8192
    Write-Host "[qoder] -Thinking enabled 需要预算 ⇒ 自动补 --thinking-budget $ThinkingBudget" -ForegroundColor Yellow
}
if ($Thinking)             { $extra += @('--thinking', $Thinking) }
if ($ReasoningEffort)      { $extra += @('--reasoning-effort', $ReasoningEffort) }
if ($ThinkingBudget -gt 0) { $extra += @('--thinking-budget', "$ThinkingBudget") }
if ($ContextWindow -gt 0)  { $extra += @('--context-window',  "$ContextWindow") }
if ($MaxOutputTokens -gt 0){ $extra += @('--max-output-tokens', "$MaxOutputTokens") }

$toolList = @()
if ($AllowedTools) { $toolList += ($AllowedTools -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }) }
if ($AllowWeb) {
    # 实测（2026-10-18，两次）：默认权限模式下 WebFetch 是"需要审批但不弹窗"⇒ 直接失败；
    # 只要把权限模式切成 bypass_permissions，联网就通了。
    # ⚠️ **不要再加 --allowed-tools**：它是**排他白名单** —— 列了 WebFetch/WebSearch 之后，
    #    Bash/Write/Edit 等全部被禁，连回执都写不出来（第一次就是这么翻车的：
    #    Flash 报"WebSearch/WebFetch 均被拒、写盘全被拒"）。
    #    真正要白名单时才用 -AllowedTools 显式指定。
    if ($PermissionMode -notin @('bypass_permissions')) {
        Write-Host "[qoder] -AllowWeb：把权限模式从 $PermissionMode 改成 bypass_permissions（联网工具需要它）" -ForegroundColor Yellow
        $PermissionMode = 'bypass_permissions'
    }
    # 实测（2026-10-18 第三次）：光靠 bypass_permissions，联网工具**仍会弹**
    #   `Allow searching the web?` 这样的确认，无人值守下直接失败。
    #   必须再加 --dangerously-skip-permissions 才真正无声放过。
    $extra += @('--dangerously-skip-permissions')
}
foreach ($t in $toolList) { $extra += @('--allowed-tools', $t) }
if ($McpConfig) { $extra += @('--mcp-config', $McpConfig) }
if ($Login) {
    Write-Host "[qoder] 即将进入登录流程（会弹浏览器，这一步必须人工完成）" -ForegroundColor Yellow
    & $node $cli login 2>&1 | Write-Host
    exit $LASTEXITCODE
}

if (-not $Task -or $Task.Count -eq 0) {
    Write-Host "没给 -Task。可派的活：" -ForegroundColor Yellow
    Get-ChildItem (Join-Path $Root '派活') -Filter 'Q*.md' | ForEach-Object { "  " + $_.Name }
    exit 2
}

# ── 取出「铁律」段落 ────────────────────────────────────────────────
$rulesPath = Join-Path $Root '派活\README.md'
if (-not (Test-Path $rulesPath)) { throw "找不到 $rulesPath" }
$readme = Get-Content $rulesPath -Raw -Encoding UTF8
$m = [regex]::Match($readme, '(?s)<!--\s*RULES:BEGIN\s*-->(.*?)<!--\s*RULES:END\s*-->')
if (-not $m.Success) { throw "在派活\README.md 里找不到 RULES:BEGIN/END 标记" }
$rules = $m.Groups[1].Value.Trim()

$logDir = 'E:\fudanwei\_logs\qoder'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

$okDirs = @($AddDir | Where-Object { $_ -and (Test-Path $_) })
$fail = 0

foreach ($t in $Task) {
    $taskFile = if (Test-Path $t) { (Resolve-Path $t).Path } else { Join-Path $Root ('派活\' + $t) }
    if (-not (Test-Path $taskFile)) { Write-Host "[qoder] 找不到任务书：$t" -ForegroundColor Red; $fail++; continue }

    $taskText = (Get-Content $taskFile -Raw -Encoding UTF8).Trim()
    $ts   = Get-Date -Format 'yyyyMMdd_HHmmss'
    $name = [IO.Path]::GetFileNameWithoutExtension($taskFile)
    $log  = Join-Path $logDir ("{0}_{1}.log" -f $name, $ts)

    Write-Host ""
    Write-Host ("[qoder] ==== 派活：{0} ====" -f $name) -ForegroundColor Cyan

    # ── 守卫：输入体量 ──────────────────────────────────────────
    # 只计量「输入」段：任务书可用 <!-- INPUTS --> ... <!-- /INPUTS --> 圈出真正的输入文件。
    # 否则正文里"顺便提一句"的文件名也会被算进去（Q1z 的索引表就误伤过：把 186 KB 的
    # 批次产出当成输入，导致切片白做、守卫误拒）。
    $mi = [regex]::Match($taskText, '(?s)<!--\s*INPUTS\s*-->(.*?)<!--\s*/INPUTS\s*-->')
    $measureText = if ($mi.Success) { $mi.Groups[1].Value } else { $taskText }
    $measure = Measure-DeclaredInput -Text $measureText -Roots (@($okDirs) + @($Root) + @((Join-Path $Root '派活\产出')))
    if ($measure.TotalKB -gt 0) {
        Write-Host ("[qoder] 声明输入 {0} 个文件，合计 {1} KB（上限 {2} KB）" -f $measure.Rows.Count, $measure.TotalKB, $MaxInputKB) -ForegroundColor DarkGray
        if ($measure.TotalKB -gt $MaxInputKB -and -not $Force) {
            Write-Host ("[qoder] 拒绝派活：输入 {0} KB > 上限 {1} KB。" -f $measure.TotalKB, $MaxInputKB) -ForegroundColor Red
            Write-Host "         小模型上下文一长就会漂移。请拆批（见 派活\README.md 铁律 0）；确实要跑加 -Force。" -ForegroundColor Red
            $measure.Rows | ForEach-Object { Write-Host ("           {0,-45} {1,8} KB" -f $_.File, $_.KB) }
            $fail++; continue
        }
    }

    $prompt = @"
你是一名被派活的工程助手。工作目录是 $Root 。
下面先给你**铁律**，再给你**任务书**。铁律优先于任务书里任何与之冲突的表述。

============================ 铁律 ============================
$rules

============================ 任务书 ============================
$taskText

============================ 开始 ============================
⚠️ 你是一个**小模型（$Model）**：输入一长，注意力就会漂移，会开始编。
因此本任务按「小步」设计，你必须遵守：
1. **一次只读一份输入文件、或一个指定片段**；读完**立刻**把结论写进产出文件（落盘）。
2. 写盘之后**只依赖你自己写下的内容**，**不要**把原文反复读回上下文。
3. 每写完一节，在节末写一行「**压缩要点**：<不超过 100 字>」；后面的小节只引用这行。
4. 一旦发现上下文已经很长（轮次多、读了很多文件），**立刻停止读新东西**，
   把已有内容写盘，并在文件末尾写「**本批未完成的部分**」逐条列出。
5. **宁可交一份短而准的产出，也不要为了"做全"而长程硬撑**——长程硬撑出来的产出会开始编造。

注意：你的文件访问被限制在工作目录内。本次已用 --add-dir 额外授权下面这些目录的**只读**访问，
任务书里凡是写到这些目录下的输入文件，都在授权范围内，直接读即可：
$((($okDirs) -join "`n") )
（如果某个输入目录不在上面这个列表里、又确实读不到，就按上面第 4、5 条的口径**如实**写「不确定」，
  **不要**去尝试绕过权限层，也不要编造内容。）

先用你自己的文件读取工具确认输入文件真实存在（**尽量不用 shell 命令**，这是无人值守执行），
再逐份真读，最后按任务书要求写产出文件。
不要问我问题（这是无人值守执行）；遇到不确定的，写「不确定」并继续（对应上面第 4、5 条）。
全部写完后，用不超过 15 行总结：新建了哪些文件、哪些没做成、需要人确认什么。
"@

    if ($skillPath) {
        $prefix = @"
【开工前必做】先完整读一遍这个技能文件，再开始干活：
  $(Join-Path $skillPath 'SKILL.md')
它是本项目的审计规矩（报数口径 / 可信度标注 / 回执格式 / 已知的 CLI 坑）。
读完在心里遵守它；**不要在回执里复述它**。

"@
        $prompt = $prefix + $prompt
    }

    $promptFile = Join-Path $logDir ("{0}_{1}.prompt.txt" -f $name, $ts)
    [IO.File]::WriteAllText($promptFile, $prompt, (New-Object Text.UTF8Encoding($true)))

    Write-Host ("[qoder] 任务书   : {0}" -f $taskFile) -ForegroundColor DarkGray
    Write-Host ("[qoder] 模型     : {0}" -f $Model) -ForegroundColor DarkGray
    Write-Host ("[qoder] 权限模式 : {0}" -f $PermissionMode) -ForegroundColor DarkGray
    if ($extra.Count -gt 0) { Write-Host ("[qoder] 额外参数 : {0}" -f ($extra -join ' ')) -ForegroundColor DarkGray }
    if ($skillPath) { Write-Host ("[qoder] 技能     : {0}" -f $skillPath) -ForegroundColor DarkGray }
    Write-Host ("[qoder] prompt   : {0}  ({1} 字符)" -f $promptFile, $prompt.Length) -ForegroundColor DarkGray
    Write-Host ("[qoder] 额外授权 : {0}" -f ($okDirs -join ' | ')) -ForegroundColor DarkGray
    Write-Host ("[qoder] 超时     : {0} 秒" -f $TimeoutSec) -ForegroundColor DarkGray
    Write-Host ("[qoder] 日志     : {0}" -f $log) -ForegroundColor DarkGray

    if ($DryRun) { Write-Host "[qoder] -DryRun：只拼 prompt，不调用。" -ForegroundColor Yellow; continue }

    # ── 执行（prompt 走文件，避免 Start-Job 吃引号）────────────────
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $job = Start-Job -ScriptBlock {
        param($nodeExe, $cliPath, $pFile, $cwd, $perm, $dirs, $mdl, $extraArgs)
        # Qoder 输出是 UTF-8；Start-Job 里的控制台默认按本地代码页解码，中文会变乱码，
        # 而且乱码会被原样写进 .log。这里必须在**作业内部**设一次。
        try { [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false) } catch { }
        $p = [IO.File]::ReadAllText($pFile, (New-Object Text.UTF8Encoding($true)))
        $a = @($cliPath, '-p', $p, '--cwd', $cwd, '--permission-mode', $perm, '--no-session-persistence')
        foreach ($d in $dirs) { $a += @('--add-dir', $d) }
        if ($mdl) { $a += @('-m', $mdl) }
        if ($extraArgs) { $a += $extraArgs }
        & $nodeExe @a 2>&1 | Out-String
    } -ArgumentList $node, $cli, $promptFile, $Root, $PermissionMode, $okDirs, $Model, $extra

    $finished = Wait-Job $job -Timeout $TimeoutSec
    $timedOut = $false
    if (-not $finished) { $timedOut = $true; Stop-Job $job }
    $out = (Receive-Job $job 2>&1 | Out-String)
    Remove-Job $job -Force
    $sw.Stop()

    $header = @(
        "### 任务 $name"
        "### 时间 $ts"
        "### 模型 $Model"
        "### 权限模式 $PermissionMode"
        "### 超时设置 $TimeoutSec 秒"
        "### 实际耗时 $([int]$sw.Elapsed.TotalSeconds) 秒"
        "### 是否超时 $timedOut"
        ""
    ) -join "`n"
    [IO.File]::WriteAllText($log, $header + $out, (New-Object Text.UTF8Encoding($true)))

    if ($timedOut) {
        Write-Host ("[qoder] 超时 {0} 秒，已 Kill。这通常意味着它在长程硬撑 / 漂移。" -f $TimeoutSec) -ForegroundColor Red
        Write-Host "        处置：把任务再拆小，检查任务书是不是让它读了太多东西。" -ForegroundColor Red
        $fail++
    } else {
        Write-Host ("[qoder] 耗时 {0}s" -f [int]$sw.Elapsed.TotalSeconds) -ForegroundColor Cyan
    }

    $lines = $out -split "`r?`n"
    $tail  = if ($lines.Count -gt 40) { $lines[($lines.Count-40)..($lines.Count-1)] } else { $lines }
    Write-Host "---- 输出末尾 ----" -ForegroundColor DarkGray
    $tail | Write-Host
    Write-Host "---- 完整日志见上面路径 ----" -ForegroundColor DarkGray
}

exit $fail
