#requires -Version 5.1
<#
    check_ps1.ps1 -- verify every .ps1 in this repo is loadable by Windows PowerShell 5.1.

    WHY THIS EXISTS
    Windows PowerShell 5.1 reads a .ps1 as ANSI unless the file starts with a UTF-8 BOM.
    Any .ps1 containing non-ASCII text (e.g. Chinese comments or strings) therefore
    FAILS TO PARSE when the BOM is lost -- and the `edit` tool strips BOMs.
    That is exactly how the qoder.ps1 dispatcher got broken on 2026-09-18: two
    dispatches died instantly with "Missing ')' in function parameter list".

    RULE: after editing any .ps1 that contains non-ASCII characters, re-add the BOM:

        $p = '<file>'
        $t = [IO.File]::ReadAllText($p, [Text.UTF8Encoding]::new($false))
        [IO.File]::WriteAllText($p, $t, (New-Object Text.UTF8Encoding($true)))

    ...then run this script.

    NOTE: this script is deliberately ASCII-ONLY, including its default Root -- which is
    derived from the script's own location instead of being hardcoded, because the repo
    path contains non-ASCII characters. A BOM checker that itself needs a BOM is useless.

    Exit code: 0 = all good, 1 = at least one problem.
#>
[CmdletBinding()]
param([string]$Root)

$ErrorActionPreference = 'Stop'

if (-not $Root) {
    # $PSScriptRoot is  <repo>\Tools  ->  the repo root is its parent.
    if (-not $PSScriptRoot) { throw 'Run this with -File so $PSScriptRoot is available, or pass -Root.' }
    $Root = Split-Path -Parent $PSScriptRoot
}

$files = Get-ChildItem $Root -Recurse -File -Filter *.ps1 -ErrorAction SilentlyContinue |
         Where-Object { $_.FullName -notlike '*\.git\*' }

$bad = 0
foreach ($f in $files) {
    $bytes  = [IO.File]::ReadAllBytes($f.FullName)
    $hasBom = ($bytes.Length -ge 3 -and $bytes[0] -eq 239 -and $bytes[1] -eq 187 -and $bytes[2] -eq 191)
    $text   = [IO.File]::ReadAllText($f.FullName, (New-Object Text.UTF8Encoding($false)))
    $nonAscii = [bool]($text -match '[^\x00-\x7F]')

    $bomState = 'BOM-ok'
    if ($nonAscii -and -not $hasBom) { $bomState = 'MISSING-BOM'; $bad++ }
    elseif (-not $hasBom)            { $bomState = 'ascii-no-bom' }

    $parseState = 'parse-ok'
    try { $null = [ScriptBlock]::Create($text) }
    catch { $parseState = 'PARSE-FAIL'; $bad++ }

    "{0,-12} {1,-11} {2}" -f $bomState, $parseState, $f.Name
}

"---- {0} script(s), {1} problem(s) ----" -f $files.Count, $bad
if ($bad -gt 0) { exit 1 }
