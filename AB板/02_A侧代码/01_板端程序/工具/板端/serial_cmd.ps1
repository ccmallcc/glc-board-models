param(
    [string]$Cmd = "echo SERIAL_OK",
    [string]$CmdFile = "",
    [string]$OutFile = "",
    [string]$Port = "COM3",
    [int]$Baud = 115200,
    [int]$WaitMs = 8000,
    [switch]$ShowHandshake
)

# 长命令/含引号命令用 -CmdFile 传入（文件内容就是要在板子上执行的整行）
if ($CmdFile -ne "") {
    $Cmd = (Get-Content -Raw -Encoding UTF8 $CmdFile).TrimEnd("`r", "`n")
}

# 串口执行一条命令：发出去 -> 定时收全 -> 去掉回显行 -> 打印
# 不用"结束标记"，因为标记会出现在被回显的命令行里，导致提前判定结束（踩过）
$sp = New-Object System.IO.Ports.SerialPort $Port, $Baud, 'None', 8, 'One'
$sp.ReadTimeout = 300
$sp.WriteTimeout = 1000
try { $sp.Open() } catch { Write-Output "打开 $Port 失败: $($_.Exception.Message)"; exit 1 }
Start-Sleep -Milliseconds 200
$sp.DiscardInBuffer(); $sp.DiscardOutBuffer()

if ($ShowHandshake) {
    $sp.Write("`r`n"); Start-Sleep -Milliseconds 500
    $hs = $sp.ReadExisting()
    Write-Output "----- 握手 -----"
    Write-Output (($hs -split "`n") -join "`n")
}

$sp.Write("$Cmd`r`n")
$sb = New-Object System.Text.StringBuilder
$deadline = (Get-Date).AddMilliseconds($WaitMs)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 150
    $chunk = $sp.ReadExisting()
    if ($chunk) { [void]$sb.Append($chunk) }
}
$sp.Close()

$raw = $sb.ToString() -replace "`r", ""
$lines = $raw -split "`n"
# 去掉回显的命令行本身。
# Q9-#6：命令被终端折行回显时，碎片会漏进来 —— 这里把"整行是命令开头一段"的碎片也剔掉。
$out = $lines | Where-Object {
    $t = $_.Trim()
    if ($t -eq '' -or $t -eq $Cmd.Trim()) { return $false }
    if ($t.Length -ge 6 -and $Cmd.Trim().StartsWith($t)) { return $false }
    return $true
}
if ($OutFile -ne "") {
    # 原样落盘（保留回显，便于事后核对），并只打印首尾各 3 行
    # Q9-#7：显式 UTF8，避免 Windows PowerShell 5.1 默认 ANSI 把中文写坏
    Set-Content -Path $OutFile -Value $raw -Encoding UTF8
    Write-Output "已写 $OutFile ($((Get-Item $OutFile).Length) B)"
    Write-Output "----- 首 3 行 -----"
    Write-Output (($lines | Where-Object { $_.Trim() -ne "" } | Select-Object -First 3) -join "`n")
    Write-Output "----- 末 3 行 -----"
    Write-Output (($lines | Where-Object { $_.Trim() -ne "" } | Select-Object -Last 3) -join "`n")
    exit 0
}
Write-Output "----- 输出 -----"
Write-Output (($out -join "`n").Trim())
