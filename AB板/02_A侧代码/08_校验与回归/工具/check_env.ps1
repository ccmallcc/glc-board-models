# check_env.ps1 —— GLC 项目环境一键自检
#
# 用法（在任意 PowerShell 窗口）：
#     powershell -ExecutionPolicy Bypass -File "E:\fudanwei\GLC-共享包\工具\check_env.ps1"
#
# 输出一张 ✔ / ✘ 表。✘ 的项请对照 04_环境安装指南.md 第六节排查。
# 本脚本只读不写，不会修改任何东西。

$ErrorActionPreference = 'SilentlyContinue'
$env:WSL_UTF8 = 1

$script:pass = 0
$script:fail = 0
$script:warn = 0
$rows = New-Object System.Collections.ArrayList

function Add-Row {
    param([string]$Item, [string]$Expect, [string]$Got, [string]$State)
    if ($State -eq 'OK')   { $script:pass++ }
    elseif ($State -eq 'WARN') { $script:warn++ }
    else                   { $script:fail++ }
    $mark = if ($State -eq 'OK') { '[OK]  ' } elseif ($State -eq 'WARN') { '[WARN]' } else { '[FAIL]' }
    [void]$rows.Add([pscustomobject]@{ Mark = $mark; Item = $Item; Expect = $Expect; Got = $Got })
}

function Test-File($path, $item, $expect) {
    if (Test-Path $path) { Add-Row $item $expect 'found' 'OK' }
    else { Add-Row $item $expect 'MISSING' 'FAIL' }
}

Write-Host ''
Write-Host '============================================================'
Write-Host ' GLC 项目环境自检'
Write-Host '============================================================'

# ---------- 1. 官方资料 ----------
Write-Host ''
Write-Host '--- 1. 官方资料 ---'
Test-File 'E:\fudanwei\官方资料\2026嵌赛\03_FMQL30TAI-悟净开发板手册' '硬件手册目录' '存在'
Test-File 'E:\fudanwei\官方资料\2026嵌赛\06_板载Linux系统镜像' 'SD 镜像目录' '存在'

# ---------- 2. 主机侧工具链 ----------
Write-Host '--- 2. 主机侧工具链 ---'
$icraft = 'E:\fudanwei\Icraft-3.36.1\bin\icraft.exe'
Test-File $icraft 'Icraft 主程序' '存在'
if (Test-Path $icraft) {
    # 注意：icraft --help 打印的是「通用转发帮助」，并不列出子命令名，
    # 所以判据是「有输出」而不是「含 parse/quantize」。
    $out = (& $icraft --help 2>&1 | Out-String)
    if ($out.Length -gt 50) {
        Add-Row 'Icraft --help 可用' '有输出（不校验子命令名）' ("{0} 字符" -f $out.Length) 'OK'
    } else {
        Add-Row 'Icraft --help 可用' '有输出' '无输出/异常' 'FAIL'
    }
    # 再用一个子命令确认真能干活
    $qexe = 'E:\fudanwei\Icraft-3.36.1\bin\icraft-quantize.exe'
    if (Test-Path $qexe) {
        $qo = (& $qexe --help 2>&1 | Out-String)
        if ($qo.Length -gt 50) { Add-Row 'icraft-quantize --help 可用' '有输出' ("{0} 字符" -f $qo.Length) 'OK' }
        else { Add-Row 'icraft-quantize --help 可用' '有输出' '无输出/异常' 'FAIL' }
    }
}
foreach ($t in @(
    @{p='E:\fudanwei\Icraft-3.36.1\bin\icraft-quantize.exe'; n='icraft-quantize'},
    @{p='E:\fudanwei\Icraft-3.36.1\bin\icraft-generate.exe'; n='icraft-generate'},
    @{p='E:\fudanwei\Icraft-3.36.1\bin\icraft-run.exe';      n='icraft-run'})) {
    Test-File $t.p $t.n '存在'
}
Test-File 'E:\fudanwei\Procise\procise_launch.exe' 'Procise（做 PL 才需要）' '存在'
Test-File 'E:\fudanwei\tools\7-Zip\7z.exe' '7-Zip' '存在'
Test-File 'E:\fudanwei\tools\cmake-3.31.6-windows-x86_64\bin\cmake.exe' 'CMake 3.31.6' '存在'
Test-File 'E:\fudanwei\tools\Netron-app\Netron.exe' 'Netron' '存在'

# ---------- 3. Python 环境 ----------
Write-Host '--- 3. Python 环境 ---'
$glcPy = 'E:\fudanwei\envs\glc\python.exe'
if (Test-Path $glcPy) {
    $v = & $glcPy -c "import sys,torch;print(sys.version.split()[0],torch.__version__,torch.cuda.is_available())" 2>&1 | Out-String
    $v = $v.Trim()
    if ($v -match 'True') { Add-Row 'envs\glc (torch+CUDA)' 'py3.12 torch2.5.1 CUDA True' $v 'OK' }
    elseif ($v -match 'torch') { Add-Row 'envs\glc (torch+CUDA)' 'CUDA True' $v 'WARN' }
    else { Add-Row 'envs\glc (torch+CUDA)' '可导入 torch' $v 'FAIL' }
} else { Add-Row 'envs\glc' '存在' 'MISSING' 'FAIL' }

$fpaiPy = 'E:\fudanwei\envs\fpai38\python.exe'
if (Test-Path $fpaiPy) {
    $v = & $fpaiPy -c "import sys,icraft;print('py'+sys.version.split()[0]+' icraft OK')" 2>&1 | Out-String
    $v = $v.Trim()
    if ($v -match 'icraft OK') { Add-Row 'envs\fpai38 (icraft API)' '可导入 icraft' $v 'OK' }
    else { Add-Row 'envs\fpai38 (icraft API)' '可导入 icraft' $v 'WARN' }
} else { Add-Row 'envs\fpai38' '存在（可选）' 'MISSING' 'WARN' }

# ---------- 4. WSL 发行版 ----------
Write-Host '--- 4. WSL 发行版 ---'
$distros = (wsl -l -q 2>$null | Out-String)
foreach ($d in @('FPAI-Ubuntu2004', 'Ubuntu-22.04')) {
    if ($distros -match [regex]::Escape($d)) { Add-Row "WSL $d 已安装" '已安装' 'found' 'OK' }
    else { Add-Row "WSL $d 已安装" '已安装' 'MISSING' 'FAIL' }
}

# 交叉编译环境
$v = (wsl -d FPAI-Ubuntu2004 -- bash -lc "aarch64-linux-gnu-gcc --version 2>/dev/null | head -1" 2>$null | Out-String).Trim()
if ($v -match 'aarch64') { Add-Row 'FPAI-Ubuntu2004 交叉编译器' 'aarch64-linux-gnu-gcc' ($v -replace '\s+',' ').Substring(0,[Math]::Min(46,($v -replace '\s+',' ').Length)) 'OK' }
else { Add-Row 'FPAI-Ubuntu2004 交叉编译器' 'aarch64-linux-gnu-gcc' 'NOT FOUND' 'FAIL' }

# 熵编码环境
$v = (wsl -d Ubuntu-22.04 -- python3 -c "import compressai,torch;print(compressai.__version__, torch.__version__, torch.cuda.is_available())" 2>$null | Out-String).Trim()
if ($v -match '^1\.2\.8') { Add-Row 'Ubuntu-22.04 compressai' '1.2.8 + torch' $v 'OK' }
elseif ($v -match 'compressai|No module') { Add-Row 'Ubuntu-22.04 compressai' '1.2.8' $v 'FAIL' }
else { Add-Row 'Ubuntu-22.04 compressai' '1.2.8' 'import 失败' 'FAIL' }

# ---------- 5. 工作区关键产物 ----------
Write-Host '--- 5. 工作区关键产物 ---'
$W = 'E:\fudanwei\工作区'
Test-File "$W\GLC-main\GLC-main\pretrained\GLC_image.pth.tar" 'GLC 权重（667MB）' '存在'
Test-File "$W\testset\kodak_real\kodim01.png" '真 Kodak 测试集' '存在'
Test-File "$W\compile2\s1_bf16\gen\s1_encoder_ga_hyper_ZG.json" '编译产物 S1 (bf16)' '存在'
Test-File "$W\rans\glc_cdf_table.h" '板端 CDF 常量表' '存在'
Test-File "$W\rans\glc_board_encoder.h" '板端熵编码器' '存在'
Test-File "$W\v3\v3_manifest.json" '回归向量集' '存在'

# 检查测试集是否真的是照片（防止再拿错）
$kodak = "$W\testset\kodak_real\kodim01.png"
if (Test-Path $kodak) {
    $sz = (Get-Item $kodak).Length
    if ($sz -gt 300000) { Add-Row 'Kodak 图片大小体检' '>300KB（真照片）' "$([math]::Round($sz/1KB))KB" 'OK' }
    else { Add-Row 'Kodak 图片大小体检' '>300KB（真照片）' "$([math]::Round($sz/1KB))KB 偏小，可能又拿错了" 'WARN' }
}

# ---------- 汇总 ----------
Write-Host ''
Write-Host '============================================================'
Write-Host ' 结果'
Write-Host '============================================================'
$rows | Format-Table -AutoSize -Property Mark, Item, Expect, Got

Write-Host ("  通过 {0} 项 ｜ 警告 {1} 项 ｜ 失败 {2} 项" -f $script:pass, $script:warn, $script:fail)
Write-Host ''
if ($script:fail -eq 0) {
    Write-Host '  ✔ 环境检查通过，可以开始工作。'
    Write-Host '  下一步：读 08_踩过的坑与注意事项.md，然后从 06_接下来要做什么.md 认领任务。'
} else {
    Write-Host '  ✘ 有失败项。请对照 04_环境安装指南.md 第六节「常见失败对照表」排查。'
}
Write-Host ''
Write-Host '  提示：icraft --version 抛异常是已知现象，不是装坏了；用 --help 验证。'
Write-Host ''
