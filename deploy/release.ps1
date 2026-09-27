# ============================================================
# 水路运输检查平台 · 提交前一键检查 / 发布
# 用法：
#   检查（默认，不提交）：powershell -ExecutionPolicy Bypass -File deploy\release.ps1
#   检查+发布：          ... release.ps1 -Push -Message "修复xxx"
# 流程：Python 语法 → 168 项回归 → 内联 JS 语法 → 敏感文件门禁 →（可选）提交推送
# ============================================================
param(
    [switch]$Push,
    [string]$Message = "更新"
)
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$fail = 0

Write-Host "[1/4] Python 语法编译..." -ForegroundColor Cyan
$pyfiles = (Get-ChildItem routes_*.py | ForEach-Object { $_.Name }) + @('app.py','webcore.py','db.py','config.py','pdfgen.py','zipgen.py','exportgen.py','seed_items.py','smoke_test.py','js_syntax_check.py','db_maintenance.py')
python -m py_compile @pyfiles
if ($LASTEXITCODE -ne 0) { $fail++; Write-Host "  ✗ 编译失败" -ForegroundColor Red } else { Write-Host "  ✓ OK" -ForegroundColor Green }

Write-Host "[2/4] 全量回归 smoke_test..." -ForegroundColor Cyan
python smoke_test.py *> "$env:TEMP\slys_release_test.txt"
$smk = Get-Content "$env:TEMP\slys_release_test.txt" -Raw
if ($LASTEXITCODE -ne 0 -or $smk -notmatch "通过") { $fail++; Write-Host "  ✗ 回归未通过" -ForegroundColor Red; $smk | Select-String 'FAIL' } else { Write-Host "  ✓ $($smk.Trim().Split("`n")[-1])" -ForegroundColor Green }

Write-Host "[3/4] 内联 JS 语法..." -ForegroundColor Cyan
python js_syntax_check.py
if ($LASTEXITCODE -ne 0) { $fail++; Write-Host "  ✗ JS 语法错误" -ForegroundColor Red } else { Write-Host "  ✓ OK" -ForegroundColor Green }

Write-Host "[4/4] 敏感文件门禁（data/密钥/库文件不得入库）..." -ForegroundColor Cyan
$dirty = git status --porcelain | Select-String -Pattern 'data/|data\\|secret|\.db$|\.db-wal|\.db-shm'
if ($dirty) { $fail++; Write-Host "  ✗ 以下条目疑似敏感：" -ForegroundColor Red; $dirty } else { Write-Host "  ✓ OK" -ForegroundColor Green }

if ($fail -gt 0) {
    Write-Host "`n== 检查未通过（$fail 项），已阻止提交 ==" -ForegroundColor Red
    exit 1
}
Write-Host "`n== 检查全绿 ==" -ForegroundColor Green

if ($Push) {
    git add -A
    git commit -m $Message
    git push
    Write-Host "已推送：$Message" -ForegroundColor Green
} else {
    Write-Host "（未推送。确认无误后用：release.ps1 -Push -Message `"说明`"）"
}
