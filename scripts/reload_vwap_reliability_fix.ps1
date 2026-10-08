param([switch]$DryRun)
$ErrorActionPreference = 'Stop'
$taskProject = Split-Path $PSScriptRoot -Parent
$taskMarker = 'VWAP reliability: bounded database reads and broker recovery v2.'
if (-not (Select-String -LiteralPath (Join-Path $taskProject 'vwap_executor.py') -SimpleMatch $taskMarker -Quiet)) {
    throw 'Reliability patch startup marker is missing. Nothing stopped.'
}
if (-not $DryRun) {
    $taskPrincipal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $taskPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Administrator PowerShell is required to reload the SYSTEM worker. Nothing stopped.'
    }
}
& (Join-Path $PSScriptRoot 'reload_vwap_weekend_fix.ps1') -DryRun:$DryRun -ExpectedMarker $taskMarker -WaitSeconds 180
