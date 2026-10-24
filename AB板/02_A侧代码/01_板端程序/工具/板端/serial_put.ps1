# 串口上传文件（base64 分块），带 md5 校验。
# 为什么需要它：板子唯一网口给相机了，改脚本/UI 只能走 COM3（实测 11.10 KB/s）。
# 早先的做法是"每块都调一次 serial_cmd.ps1"，那样每块都要重开串口 + 等 WaitMs，
# 25 KB 的文件要 1 分钟以上；这里**一次开串口、连续写**，同样内容 3~5 秒。
#
# 用法:
#   pwsh -File 工具\板端\serial_put.ps1 -Local E:\x\glc_ui.py -Remote /root/glc_ui.py
#   pwsh -File 工具\板端\serial_put.ps1 -Local ... -Remote ... -Port COM3 -Chunk 1800
param(
    [Parameter(Mandatory=$true)][string]$Local,
    [Parameter(Mandatory=$true)][string]$Remote,
    [string]$Port = "COM3",
    [int]$Baud = 115200,
    [int]$Chunk = 1800,
    [int]$GapMs = 90
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path $Local)) { Write-Output "本地文件不存在: $Local"; exit 1 }
$bytes = [System.IO.File]::ReadAllBytes($Local)
$b64 = [Convert]::ToBase64String($bytes)
$localMd5 = (Get-FileHash -Algorithm MD5 -Path $Local).Hash.ToLower()

$tmp = "$Remote.b64"
$sp = New-Object System.IO.Ports.SerialPort $Port, $Baud, 'None', 8, 'One'
$sp.ReadTimeout = 300
$sp.WriteTimeout = 2000
try { $sp.Open() } catch { Write-Output "打开 $Port 失败: $($_.Exception.Message)"; exit 2 }
Start-Sleep -Milliseconds 250
$sp.DiscardInBuffer(); $sp.DiscardOutBuffer()

function Send-Line($line, $wait = 60) {
    $sp.Write("$line`r`n")
    Start-Sleep -Milliseconds $wait
}

# 清空 + 起一个干净的 base64 文件
Send-Line "rm -f $tmp" 300

$n = [math]::Ceiling($b64.Length / $Chunk)
$i = 0
for ($off = 0; $off -lt $b64.Length; $off += $Chunk) {
    $i++
    $piece = $b64.Substring($off, [Math]::Min($Chunk, $b64.Length - $off))
    Send-Line "printf '%s' '$piece' >> $tmp" $GapMs
    if (($i % 5) -eq 0) { Write-Output ("  已送 {0}/{1} 块" -f $i, $n) }
}
Send-Line "" 200
Send-Line "base64 -d $tmp > $Remote && rm -f $tmp && md5sum $Remote" 1200

# ★ 2026-10-23 修：原来只读 4 s，130 KB 的 glc_ui.py 上传成功后 md5 行还在回显洪流后面排队，
#   于是被误判成 PUT_FAIL（实际文件是好的，md5 一致）。改成"读到 2.5 s 没新数据为止"，最多 20 s。
$sb = New-Object System.Text.StringBuilder
$end = (Get-Date).AddMilliseconds(20000)
$lastData = Get-Date
while ((Get-Date) -lt $end) {
    Start-Sleep -Milliseconds 150
    $c = $sp.ReadExisting()
    if ($c) { [void]$sb.Append($c); $lastData = Get-Date }
    elseif (((Get-Date) - $lastData).TotalMilliseconds -gt 2500) { break }
}
$sp.Close()

$out = $sb.ToString()
Write-Output "---- 板端回显 ----"
Write-Output $out
Write-Output "本地 md5: $localMd5"
$ok = $out -match [regex]::Escape($localMd5)
if ($ok) { Write-Output "PUT_OK  $Remote  ($($bytes.Length) B)" ; exit 0 }
else { Write-Output "PUT_FAIL md5 不一致（板端没回显上面对的值）"; exit 3 }
