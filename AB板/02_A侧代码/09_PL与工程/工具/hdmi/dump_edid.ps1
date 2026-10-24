# Dump every monitor's raw EDID block from the Windows registry to .bin files
$ErrorActionPreference = 'Continue'
$out = 'E:\fudanwei\_logs\hdmi'
New-Item -ItemType Directory -Force -Path $out | Out-Null

function U2S($arr) {
  if ($null -eq $arr) { return '' }
  return (($arr | Where-Object { $_ -ne 0 } | ForEach-Object { [char]$_ }) -join '')
}

Write-Output "==================== 1. WMI monitor list ===================="
try {
  Get-CimInstance -Namespace root\wmi -ClassName WmiMonitorID -ErrorAction Stop | ForEach-Object {
    Write-Output ("  InstanceName = " + $_.InstanceName)
    Write-Output ("    MFR=[" + (U2S $_.ManufacturerName) + "]  MODEL=[" + (U2S $_.UserFriendlyName) + "]  SN=[" + (U2S $_.SerialNumberID) + "]  Year=" + $_.YearOfManufacture + "  Week=" + $_.WeekOfManufacture)
  }
} catch { Write-Output "  WmiMonitorID unavailable: $_" }

Write-Output ""
Write-Output "==================== 2. Basic display params ===================="
try {
  Get-CimInstance -Namespace root\wmi -ClassName WmiMonitorBasicDisplayParams -ErrorAction Stop | ForEach-Object {
    Write-Output ("  " + $_.InstanceName + "  MaxH=" + $_.MaxHorizontalImageSize + "cm MaxV=" + $_.MaxVerticalImageSize + "cm VideoInputType=" + $_.VideoInputType)
  }
} catch { Write-Output "  unavailable: $_" }

Write-Output ""
Write-Output "==================== 3. Raw EDID blocks in registry ===================="
$found = 0
$root = 'HKLM:\SYSTEM\CurrentControlSet\Enum\DISPLAY'
Get-ChildItem $root -ErrorAction SilentlyContinue | ForEach-Object {
  $monId = $_.PSChildName
  Get-ChildItem $_.PSPath -ErrorAction SilentlyContinue | ForEach-Object {
    $inst = $_.PSChildName
    $dp = Join-Path $_.PSPath 'Device Parameters'
    $edid = (Get-ItemProperty -Path $dp -Name EDID -ErrorAction SilentlyContinue).EDID
    if ($edid -and $edid.Length -ge 128) {
      $safe = ($inst -replace '[^A-Za-z0-9]', '_')
      $file = Join-Path $out ('edid_' + $monId + '_' + $safe + '.bin')
      [System.IO.File]::WriteAllBytes($file, [byte[]]$edid)
      Write-Output ("  " + $monId + " \ " + $inst + "   ->  " + $edid.Length + " bytes  ->  " + $file)
      $h8 = ($edid[0..7] | ForEach-Object { $_.ToString('x2') }) -join ' '
      Write-Output ("      first8bytes: " + $h8)
      $script:found = $script:found + 1
    }
  }
}
if ($found -eq 0) { Write-Output "  ** NO EDID FOUND IN REGISTRY **" }

Write-Output ""
Write-Output "==================== 4. Current active display modes ===================="
try {
  Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
  [System.Windows.Forms.Screen]::AllScreens | ForEach-Object {
    Write-Output ("  Device=" + $_.DeviceName + "  Primary=" + $_.Primary + "  Bounds=" + $_.Bounds.ToString())
  }
} catch { Write-Output "  WinForms unavailable: $_" }

Write-Output ""
Write-Output "==================== 5. Listed supported source modes ===================="
try {
  $n = 0
  Get-CimInstance -Namespace root\wmi -ClassName WmiMonitorListedSupportedSourceModes -ErrorAction Stop | ForEach-Object {
    Write-Output ("  Instance: " + $_.InstanceName)
    $i = 0
    foreach ($m in $_.MonitorSourceModes) {
      $i++
      if ($i -le 40) {
        Write-Output ("    mode[" + $i + "] PixelClock(Hz)=" + $m.PixelClockRate + "  H=" + $m.HorizontalActivePixels + "  V=" + $m.VerticalActivePixels)
      }
    }
    $n++
  }
  if ($n -eq 0) { Write-Output "  (empty)" }
} catch { Write-Output "  unavailable: $_" }
