# 验证：GLC 网络能不能跑 512x512（latent 32x32）
#
# 这一步完全不碰板子，只回答三个问题：
#   ① 导出能不能成功          （形状是否真的与尺寸无关）
#   ② 权重能不能前向          （有没有形状相关的算子）
#   ③ 数值自洽吗              （脚本自带的 model.test() vs 拆图路径对比）
#
# 脚本里 S = args.size; L = S//16; Z = L//4
#   size=256 -> latent 16x16, z 4x4   （现在板子上用的）
#   size=512 -> latent 32x32, z 8x8   ← 正好卡在作者注释的 "latent <= patch(32)" 边界

$py    = 'E:\fudanwei\envs\torch_v2.0.1\python.exe'
$tools = 'E:\fudanwei\工作区\tools\c1_export_subgraphs.py'
$repo  = 'E:\fudanwei\工作区\GLC-main\GLC-main'
$model = 'E:\fudanwei\工作区\GLC-main\GLC-main\pretrained\GLC_image.pth.tar'
$out   = 'E:\fudanwei\工作区\onnx\c1_512'

Write-Output "======================================================================"
Write-Output "  512x512 导出 + 数值自检   (latent 32x32, z 8x8)"
Write-Output "======================================================================"
Write-Output "  python : $py"
Write-Output "  输出   : $out"
Write-Output ""

$t0 = Get-Date
& $py $tools --repo $repo --model $model --out $out --q 0 --size 512 --simple_attn 2>&1
$rc = $LASTEXITCODE
$dt = ((Get-Date) - $t0).TotalSeconds

Write-Output ""
Write-Output "======================================================================"
Write-Output ("  rc=$rc   总耗时 {0:N1} s" -f $dt)
Write-Output "======================================================================"
if (Test-Path $out) {
    Get-ChildItem $out -Filter *.onnx | ForEach-Object {
        Write-Output ("  {0,-32} {1,12:N0} B  ({2:N1} MB)" -f $_.Name, $_.Length, ($_.Length/1MB))
    }
}
Write-Output "C1_512_DONE"
