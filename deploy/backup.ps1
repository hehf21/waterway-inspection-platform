# ============================================================
# 水路运输检查平台 · 定时备份脚本（Windows 计划任务用）
# 用法：
#   手动执行：powershell -ExecutionPolicy Bypass -File deploy\backup.ps1
#   定时执行：schtasks /create /tn "SLYS每日备份" /tr "powershell -ExecutionPolicy Bypass -File <平台目录>\deploy\backup.ps1" /sc daily /st 20:00
# 说明：数据库走 SQLite 热备份（不锁库）；附件/归档/密钥直接复制目录。保留最近 30 份库备份。
# 备份状态写入 data\backups\last_backup.json（每日提醒会展示最近备份）；失败时推企微机器人（SLYS_WEBHOOK_URL）。
# ============================================================
$root = Split-Path -Parent $PSScriptRoot     # 平台根目录
$py = "python"
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$dest = Join-Path $root "data\backups"
$ok = $true
$detail = ""

# 1) 数据库热备份 + 轮转（保留30份）
& $py (Join-Path $root "db_maintenance.py") backup --keep 30
if ($LASTEXITCODE -ne 0) { $ok = $false; $detail += "数据库备份失败；" }

# 2) 附件/归档/密钥目录快照（拷贝到同一备份目录，便于整体搬迁）
$snap = Join-Path $dest "files_$stamp"
foreach ($d in @("uploads", "archives")) {
  $src = Join-Path $root "data\$d"
  if (Test-Path $src) { Copy-Item $src (Join-Path $snap $d) -Recurse -Force }
}
$key = Join-Path $root "data\secret.key"
if (Test-Path $key) { Copy-Item $key $snap -Force }

# 3) 记录备份状态（平台每日提醒文案会展示最近一次备份情况）
$dbb = Get-ChildItem $dest -Filter "app_*.db" -ErrorAction SilentlyContinue | Sort-Object Name | Select-Object -Last 1
$status = @{
  time = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
  ok = $ok
  file = if ($dbb) { $dbb.Name } else { "" }
  size = if ($dbb) { $dbb.Length } else { 0 }
  detail = $detail
} | ConvertTo-Json
[System.IO.File]::WriteAllText((Join-Path $dest "last_backup.json"), $status, [System.Text.UTF8Encoding]::new($false))

if (-not $ok) {
  # 备份失败告警：推企业微信群机器人（环境变量 SLYS_WEBHOOK_URL）
  $hook = $env:SLYS_WEBHOOK_URL
  if ($hook) {
    $text = "[水路检查平台] 备份失败 " + (Get-Date -Format "yyyy-MM-dd HH:mm") + "：" + $detail + "请立即人工处理。"
    $body = @{ msgtype = "text"; text = @{ content = $text } } | ConvertTo-Json
    try {
      Invoke-RestMethod -Uri $hook -Method Post -ContentType "application/json; charset=utf-8" `
        -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) | Out-Null
    } catch {}
  }
  Write-Host "[backup] 失败：$detail"
  exit 1
}
Write-Host "[backup] 完成：$snap"
