# ======================================================================
# git_push.ps1 —— 自动判断"走直连还是走代理"，然后推送
# ----------------------------------------------------------------------
# 背景：本机到 GitHub 的连通性会**抖动**——直连和代理都可能通、也都可能不通，
#       而且几分钟内就能变一次。手动试很浪费时间。
#       详见 08_踩过的坑与注意事项.md 坑 14。
#
# 本脚本做的事：
#   ① 分别探测 直连 / 代理 能不能真的访问 github.com
#   ② 挑能用的那条，写进本仓库的 git 配置
#   ③ 推送；失败就重新探测再试，最多 4 轮
#   ④ 全程打印判断依据，不猜
#
# ⚠️ 关键：**端口开着不等于能用**。代理端口探测返回 True 也可能完全不转发流量，
#    所以这里一律用"真发一个 HTTPS 请求看 HTTP 码"来判定。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File "E:\fudanwei\GLC-共享包\工具\git_push.ps1"
# ======================================================================

$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Repo    = 'E:\fudanwei\GLC-共享包'
$Proxy   = 'http://127.0.0.1:7897'
$Branch  = 'main'
$MaxTry  = 4

function Write-Head([string]$t) {
    Write-Host ''
    Write-Host ('=' * 62)
    Write-Host "  $t"
    Write-Host ('=' * 62)
}

# 真发一个请求，返回 HTTP 码（'000' 表示失败）
function Get-HttpCode([string]$Url, [string]$UseProxy) {
    $curlArgs = @('-s', '-o', 'NUL', '-w', '%{http_code}', '--max-time', '10')
    if ($UseProxy) { $curlArgs += @('-x', $UseProxy) }
    else           { $curlArgs += @('--noproxy', '*') }
    $curlArgs += $Url
    $code = & curl.exe @curlArgs 2>$null
    if (-not $code) { return '000' }
    return ([string]$code).Trim()
}

# 探测两条路；返回 'direct' / 'proxy' / $null
# ⚠️ 必须探 **git 端点**而不是首页 —— 实测 2026-10-08：
#      github.com 首页  直连 200 ；
#      api.github.com   直连 000（被掐）；
#      仓库 git 端点    直连 401（= 链路通，只是没带凭据）✅
#    只探首页会误判。**401/200 都算"通"**。
function Resolve-Route {
    $gitUrl = (git -C $Repo remote get-url origin 2>$null)
    if (-not $gitUrl) { $gitUrl = 'https://github.com/ccmallcc/fpga.git' }
    $probe  = ($gitUrl.Trim().TrimEnd('/') + '/info/refs?service=git-upload-pack')
    $d = Get-HttpCode $probe ''
    $p = Get-HttpCode $probe $Proxy
    Write-Host ("  直连 git 端点 -> {0}" -f $d)
    Write-Host ("  代理 git 端点 -> {0}" -f $p)
    if ($d -eq '200' -or $d -eq '401') { return 'direct' }
    if ($p -eq '200' -or $p -eq '401') { return 'proxy'  }
    return $null
}

function Set-Route([string]$Route) {
    if ($Route -eq 'direct') {
        git -C $Repo config --local --unset http.proxy  2>$null | Out-Null
        git -C $Repo config --local --unset https.proxy 2>$null | Out-Null
        # ★★ 关键：只撤 git config 还不够！★★
        #   本机 WinINET **系统代理是开着的**
        #     HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings
        #       ProxyEnable = 1 , ProxyServer = 127.0.0.1:7897
        #   而 git-for-windows 的 schannel 后端（默认）**会直接采用系统代理**，
        #   完全无视 git 自己的 http.proxy 设置。
        #   ⇒ 实测 2026-10-08：撤掉 git config 之后 `git ls-remote` 仍然报
        #        schannel: failed to receive handshake, SSL/TLS connection failed
        #     加上 NO_PROXY=* 之后**立刻成功**（17 秒推完 6 个提交）。
        $env:NO_PROXY = '*'
        $env:no_proxy = '*'
        Write-Host '  => 走【直连】（已撤仓库代理配置，并设 NO_PROXY=* 绕过系统代理）'
    } else {
        git -C $Repo config --local http.proxy  $Proxy
        git -C $Repo config --local https.proxy $Proxy
        Remove-Item Env:NO_PROXY -ErrorAction SilentlyContinue
        Remove-Item Env:no_proxy -ErrorAction SilentlyContinue
        Write-Host "  => 走【代理 $Proxy】"
    }
}

# ---------------------------------------------------------------- 前置检查
Write-Head 'git_push.ps1 · 自动选路推送'

if (-not (Test-Path $Repo)) { Write-Host "  [X] 仓库不存在：$Repo"; exit 1 }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Write-Host '  [X] 找不到 git'; exit 1 }

$ahead = git -C $Repo rev-list --count "origin/$Branch..HEAD" 2>$null
Write-Host ("  待推送提交：{0} 个" -f $ahead)
if ([int]$ahead -eq 0) {
    Write-Host '  没有需要推送的提交，直接退出。'
    exit 0
}
git -C $Repo log --oneline "origin/$Branch..HEAD" | ForEach-Object { Write-Host "    $_" }

# ---------------------------------------------------------------- 主循环
$ok = $false
for ($try = 1; $try -le $MaxTry; $try++) {
    Write-Head ("第 $try / $MaxTry 轮")

    $route = Resolve-Route
    if (-not $route) {
        Write-Host '  [X] 两条路都不通 —— 网络在抖，等 5 秒重试'
        if ($try -lt $MaxTry) { Start-Sleep -Seconds 5; continue }
        else { break }
    }
    Set-Route $route

    Write-Host '  推送中...'
    $out = git -C $Repo push origin $Branch 2>&1
    $code = $LASTEXITCODE
    $out | Where-Object { $_ -match '\S' } | Select-Object -Last 3 | ForEach-Object { Write-Host "    $_" }

    if ($code -eq 0) { $ok = $true; break }

    Write-Host ("  [X] 推送失败（退出码 {0}），重新探测后再试" -f $code)
    if ($try -lt $MaxTry) { Start-Sleep -Seconds 4 }
}

# ---------------------------------------------------------------- 结果
Write-Head '结果'
if ($ok) {
    git -C $Repo fetch origin 2>$null | Out-Null
    $l = git -C $Repo rev-parse HEAD
    $r = git -C $Repo rev-parse "origin/$Branch"
    Write-Host ("  [OK] 推送成功")
    Write-Host ("  本地 = {0}" -f $l.Substring(0,7))
    Write-Host ("  远端 = {0}" -f $r.Substring(0,7))
    Write-Host ("  一致 = {0}" -f ($l -eq $r))
    exit 0
} else {
    Write-Host '  [X] 试了多轮仍未成功。'
    Write-Host ''
    Write-Host '  提交都在本地，没有丢。可以：'
    Write-Host '    ① 过几分钟再跑一次本脚本'
    Write-Host '    ② 检查代理软件是否正常运行（若在用它）'
    Write-Host '    ③ 换个网络（手机热点）再试'
    Write-Host ''
    Write-Host '  手动诊断：'
    Write-Host ('    curl.exe -s -o NUL -w "%{http_code}" --max-time 10 --noproxy "*" https://github.com')
    Write-Host ('    curl.exe -s -o NUL -w "%{http_code}" --max-time 10 -x ' + $Proxy + ' https://github.com')
    exit 1
}
