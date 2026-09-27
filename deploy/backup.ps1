# 水路运输检查平台 · 定时备份脚本（Windows 计划任务用）
# 用法：
#   手动执行：powershell -ExecutionPolicy Bypass -File deploy\backup.ps1
#   定时执行：schtasks /create /tn "SLYS每日备份" /tr "powershell -ExecutionPolicy Bypass -File <平台目录>\deploy\backup.ps1" /sc daily /st 20:00
# 说明：数据库走 SQLite 热备份（不锁库）；附件/归档/密钥直接复制目录。保留最近 30 份库备份。
$root = Split-Path -Parent $PSScriptRoot     # 平台根目录
$py = "python"
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$dest = Join-Path $root "data\backups"

# 1) 数据库热备份 + 轮转（保留30份）
& $py (Join-Path $root "db_maintenance.py") backup --keep 30

# 2) 附件/归档/密钥目录快照（拷贝到同一备份目录，便于整体搬迁）
$snap = Join-Path $dest "files_$stamp"
foreach ($d in @("uploads", "archives")) {
  $src = Join-Path $root "data\$d"
  if (Test-Path $src) { Copy-Item $src (Join-Path $snap $d) -Recurse -Force }
}
$key = Join-Path $root "data\secret.key"
if (Test-Path $key) { Copy-Item $key $snap -Force }
Write-Host "[backup] 完成：$snap"
