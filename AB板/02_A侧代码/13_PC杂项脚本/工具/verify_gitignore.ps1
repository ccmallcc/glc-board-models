# 验证 .gitignore 不会误伤需要共享的文件
# 会在 GLC-共享包 里初始化一个本地 git 仓库（供你直接 push 用）
#
# ⚠️ 修正记录（2026-09-12）：
#   修正一：`git status --porcelain` 默认把**未跟踪的目录折叠成一行**（assets/ 只算 1 行），
#           数"行数"得到的**不是文件数**。必须加 `--untracked-files=all`。
#           旧版本因此会把 140 个文件报成 14 个。
#   修正二：不能只数"未跟踪"文件。**一旦提交过，未跟踪列表就是空的**，
#           旧版本会报"将被跟踪 0 个"。必须改成 已入库(git ls-files) + 新增未跟踪。
$S = 'E:\fudanwei\GLC-共享包'
Push-Location $S

git init -q 2>&1 | Out-Null

$tracked   = @(git ls-files)                                                  # 已入库
$status    = @(git status --porcelain --untracked-files=all 2>$null)          # 有变化的
$untracked = @($status  | Where-Object { $_ -match '^\?\?' })                 # 新增、尚未入库
$ignored   = @(git status --porcelain --untracked-files=all --ignored 2>$null |
               Where-Object { $_ -match '^!!' })                              # 被 .gitignore 挡掉

# 磁盘上的真实文件数（排除 .git），用于交叉核对
$physical = @(Get-ChildItem $S -Recurse -File -Force -ErrorAction SilentlyContinue |
              Where-Object { $_.FullName -notmatch '\\\.git\\' })

$total = $tracked.Count + $untracked.Count

Write-Host ("  已入库    : {0} 个文件" -f $tracked.Count)
Write-Host ("  新增待入库: {0} 个文件" -f $untracked.Count)
Write-Host ("  会被忽略  : {0} 个" -f $ignored.Count)
Write-Host ("  磁盘上实际: {0} 个文件" -f $physical.Count)
Write-Host ("  => 仓库将包含 {0} 个文件" -f $total)

if (($ignored.Count -eq 0) -and ($total -eq $physical.Count)) {
    Write-Host '  [OK] 数量吻合，且没有任何文件被忽略' -ForegroundColor Green
} else {
    Write-Host ("  [!] 不吻合或有忽略项：入库 {0} + 新增 {1} + 忽略 {2} = {3}，磁盘 {4}" -f `
        $tracked.Count, $untracked.Count, $ignored.Count, ($total + $ignored.Count), $physical.Count) -ForegroundColor Yellow
}

if ($ignored.Count -gt 0) {
    Write-Host '  --- 被忽略的（前 15 个）---'
    $ignored | Select-Object -First 15 | ForEach-Object { Write-Host "    $_" }
}

if ($untracked.Count -gt 0) {
    Write-Host '  --- 新增待入库的（前 15 个）---'
    $untracked | Select-Object -First 15 | ForEach-Object { Write-Host "    $_" }
}

Write-Host ''
Write-Host '  --- 抽查关键文件 ---'
$keyFiles = @(
    'assets/板端代码/glc_cdf_table.bin',
    'assets/板端代码/glc_cdf_table.h',
    'assets/样例码流/kodim01_q0.glc',
    'assets/图/rd_curves.png',
    'assets/官方文档摘录/sample_hardop.txt',
    '工具/check_env.ps1',
    '工具/push_to_github.ps1',
    '对外提问清单-复旦微FAE.md',
    '附录_实测报告/V6_Kodak全量基准与开销拆解报告.md',
    '附录_实测报告/NPU算子覆盖度产物级审计报告.md',
    '附录_实测报告/自定义硬算子官方机制调研报告.md',
    '07_数字口径表.md',
    '.gitignore'
)
foreach ($f in $keyFiles) {
    git check-ignore -q $f 2>$null
    if ($LASTEXITCODE -eq 0) { Write-Host "    [X] 被忽略(不应该): $f" }
    else { Write-Host "    [OK] 会跟踪: $f" }
}

Pop-Location