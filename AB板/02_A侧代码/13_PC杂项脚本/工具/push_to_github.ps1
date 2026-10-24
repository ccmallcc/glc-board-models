<#
  把 GLC-共享包 推送到 GitHub 私有仓库（一键脚本）

  用法：
    powershell -ExecutionPolicy Bypass -File .\工具\push_to_github.ps1
    powershell -ExecutionPolicy Bypass -File .\工具\push_to_github.ps1 -RepoUrl https://github.com/你的账号/仓库名.git

  本脚本会依次做完：
    ① 检查位置   ② 配代理并验证能连上 GitHub   ③ 设提交身份（缺了会问你要）
    ④ git add + commit   ⑤ 分支改成 main   ⑥ 配远端   ⑦ 推送

  重要背景（本机实测）：
    GitHub **直连不通**（15 秒超时），**必须走本机代理 127.0.0.1:7897**。
    本脚本默认把代理写进**本仓库**的 git 配置，不动全局。
#>
param(
    [string]$RepoUrl,
    [string]$Proxy = 'http://127.0.0.1:7897',
    [switch]$NoProxy
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$S = Split-Path $PSScriptRoot -Parent          # 共享包根目录
Set-Location $S

function Section($t) { Write-Host ''; Write-Host "===== $t =====" -ForegroundColor Cyan }

Section '0 / 检查位置'
Write-Host "  仓库目录: $S"
if (-not (Test-Path (Join-Path $S 'README.md'))) { throw '这里不像 GLC-共享包（找不到 README.md）' }

Section '1 / 网络（GitHub 直连不通，必须走代理）'
if (-not $NoProxy) {
    git config --local http.proxy  $Proxy
    git config --local https.proxy $Proxy
    Write-Host "  已设置仓库级代理: $Proxy"
}
$null = git ls-remote --heads https://github.com/git/git.git 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host '  [X] 连不上 GitHub。请确认代理软件在运行、端口是 ' -NoNewline -ForegroundColor Red
    Write-Host $Proxy -ForegroundColor Red
    Write-Host '      若端口不同：-Proxy http://127.0.0.1:端口' -ForegroundColor Yellow
    Write-Host '      若不用代理：-NoProxy（仅在直连可用时）' -ForegroundColor Yellow
    exit 1
}
Write-Host '  [OK] 能访问 GitHub' -ForegroundColor Green

Section '2 / 提交身份'
$name  = git config --local user.name
if (-not $name)  { $name  = git config --global user.name }
$email = git config --local user.email
if (-not $email) { $email = git config --global user.email }

if ((-not $name) -or (-not $email)) {
    Write-Host '  尚未设置提交身份（不设置的话 git commit 会直接失败）'
    Write-Host ''
    Write-Host '  GitHub 是靠【邮箱】把提交关联到你的账号的，所以建议这样填：'
    Write-Host '    昵称：你的 GitHub 用户名'
    Write-Host '    邮箱：<用户名>@users.noreply.github.com   ← 用它不会暴露真实邮箱'
    Write-Host ''
    if (-not $name)  { $name  = Read-Host '  请输入提交昵称' }
    if (-not $email) { $email = Read-Host '  请输入提交邮箱' }
    git config --local user.name  $name
    git config --local user.email $email
    Write-Host '  （只写进本仓库配置，没有改全局）'
}
Write-Host "  昵称: $name"
Write-Host "  邮箱: $email"

Section '3 / 提交'
git add -A
$staged = @(git diff --cached --name-only)
if ($staged.Count -eq 0) {
    Write-Host '  没有需要提交的改动'
} else {
    Write-Host ("  暂存 {0} 个文件" -f $staged.Count)
    git commit -q -m 'GLC 端侧部署项目共享文档'
    Write-Host '  [OK] 已提交' -ForegroundColor Green
}
git branch -M main
Write-Host '  当前分支: main'

Section '4 / 远端'
if (-not $RepoUrl) {
    Write-Host '  请先在 GitHub 网页建一个 **Private** 仓库：'
    Write-Host '    - 不要勾 "Add a README file"'
    Write-Host '    - 不要选 .gitignore 和 license'
    Write-Host '    （这样推上去不会有冲突）'
    Write-Host ''
    $RepoUrl = Read-Host '  把仓库地址粘进来（形如 https://github.com/账号/仓库名.git）'
}
$RepoUrl = "$RepoUrl".Trim()
if (-not $RepoUrl) { throw '没给仓库地址，退出' }

$existing = git remote get-url origin 2>$null
if ($existing) { git remote set-url origin $RepoUrl } else { git remote add origin $RepoUrl }
Write-Host "  origin -> $RepoUrl"

Section '5 / 推送'
Write-Host '  若弹出浏览器让你登录 GitHub，直接登录即可（Git Credential Manager）。'
Write-Host '  若它问的是"密码"，密码栏要填 **Personal Access Token**，不是账号密码。'
Write-Host ''
git push -u origin main
if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Write-Host '  [X] 推送失败。常见原因与对策：' -ForegroundColor Red
    Write-Host '      1) 认证失败：密码栏要用 PAT'
    Write-Host '         GitHub > Settings > Developer settings > Personal access tokens > Tokens(classic)'
    Write-Host '         勾 repo 权限；或先清掉旧凭据：cmdkey /list | findstr github'
    Write-Host '      2) 远端已有内容（建库时勾了 README）：git pull --rebase origin main  然后重跑本脚本'
    Write-Host '      3) 网络：确认代理软件在跑（本脚本已配 ' -NoNewline
    Write-Host "$Proxy)" -NoNewline
    Write-Host ''
    exit 1
}

Section '完成'
Write-Host "  [OK] 已推送到 $RepoUrl" -ForegroundColor Green
Write-Host '  去 GitHub 页面确认：仓库是 Private、文件数约 139 个、体积约 8.2 MB。'
Write-Host ''
Write-Host '  以后更新了内容，再跑一次本脚本即可（会自动增量提交并推送）。'