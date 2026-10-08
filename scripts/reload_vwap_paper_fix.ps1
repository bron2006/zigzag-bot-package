param([switch]$DryRun)
$ErrorActionPreference = 'Stop'
$paperRoot = Split-Path $PSScriptRoot -Parent
$paperMarker = 'VWAP paper: durable quote journal v1 (READ-ONLY branch only).'
$paperSource = Join-Path $paperRoot 'vwap_executor.py'
if (-not (Select-String -LiteralPath $paperSource -SimpleMatch $paperMarker -Quiet)) {
    throw 'Paper patch source marker missing. Nothing stopped.'
}
# Never change .env or shared runtime flags. Require an explicit static safety gate.
$paperEnv = Join-Path $paperRoot '.env'
$paperReadonly = @(Select-String -LiteralPath $paperEnv -Pattern '^\s*VWAP_EXECUTOR_READ_ONLY\s*=')
if ($paperReadonly.Count -ne 1) { throw 'One explicit READ_ONLY=true setting required. Nothing stopped.' }
$paperValue = $paperReadonly[0].Line.Split('=',2)[1].Split('#',2)[0].Trim().Trim('"').Trim("'")
if ($paperValue.ToLowerInvariant() -notin @('true','1','yes','on')) {
    throw 'Static READ_ONLY is not true. Nothing stopped; no trading mode changed.'
}
$paperPrincipal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $DryRun -and -not $paperPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Administrator PowerShell is required for the SYSTEM worker. Nothing stopped.'
}
& (Join-Path $PSScriptRoot 'reload_vwap_weekend_fix.ps1') -DryRun -ExpectedMarker $paperMarker
if ($DryRun) { Write-Output 'Paper preflight passed; nothing stopped.'; return }
$paperOldLog = Get-ChildItem (Join-Path $paperRoot 'logs') -Filter 'vwap_executor_stdout_*.log' |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $paperOldLog -or -not (Select-String -LiteralPath $paperOldLog.FullName -SimpleMatch 'Read-only: True' -Quiet)) {
    throw 'Current worker static READ_ONLY not confirmed in its stdout. Nothing stopped.'
}
$paperReloadStarted = Get-Date
& (Join-Path $PSScriptRoot 'reload_vwap_weekend_fix.ps1') -ExpectedMarker 'VWAP reliability: bounded database reads and broker recovery v2.' -WaitSeconds 180
$paperTimer = [Diagnostics.Stopwatch]::StartNew()
while ($paperTimer.Elapsed.TotalSeconds -lt 30) {
    $paperNewLog = Get-ChildItem (Join-Path $paperRoot 'logs') -Filter 'vwap_executor_stdout_*.log' |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $paperHeartbeat = Get-Item -LiteralPath (Join-Path $paperRoot 'logs\vwap_executor_heartbeat.txt') -ErrorAction SilentlyContinue
    $paperJournal = Join-Path $paperRoot 'logs\vwap_paper.sqlite3'
    if ($paperNewLog -and $paperNewLog.LastWriteTime -gt $paperReloadStarted -and
        (Select-String -LiteralPath $paperNewLog.FullName -SimpleMatch 'Read-only: True' -Quiet) -and
        (Select-String -LiteralPath $paperNewLog.FullName -SimpleMatch $paperMarker -Quiet) -and
        (Select-String -LiteralPath $paperNewLog.FullName -SimpleMatch 'Paper journal ready:' -Quiet) -and
        -not (Select-String -LiteralPath $paperNewLog.FullName -SimpleMatch 'Paper journal unavailable:' -Quiet) -and
        $paperHeartbeat -and $paperHeartbeat.LastWriteTime -gt $paperReloadStarted -and
        (Test-Path -LiteralPath $paperJournal)) {
        Write-Output 'Verified READ-ONLY paper journal ready and fresh poll heartbeat. No real orders enabled.'
        return
    }
    Start-Sleep -Seconds 1
}
throw 'Worker restart occurred but paper readiness not confirmed. Check its logs; do not start a duplicate.'
