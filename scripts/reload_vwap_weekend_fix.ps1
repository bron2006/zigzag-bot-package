param([switch]$DryRun, [string]$ExpectedMarker = 'VWAP watchdog: weekend silence enabled.',
      [ValidateRange(30,300)][int]$WaitSeconds = 60)
# Identify the executor using this project's supervisor log and process tree.
# SYSTEM command lines can be hidden; the worker uses a RELATIVE script name.
$ErrorActionPreference = 'Stop'
$paperProject = Split-Path $PSScriptRoot -Parent
$paperExecutorPath = Join-Path $paperProject 'vwap_executor.py'
$paperLogPath = Join-Path $paperProject 'logs\vwap_executor_supervisor.log'
$paperSupervisorLine = (Select-String -LiteralPath $paperLogPath -Pattern 'Supervisor started \(PID \d+\)' | Select-Object -Last 1).Line
if ($paperSupervisorLine -notmatch '^\[(?<time>[\d-]+ [\d:]+)\].*Supervisor started \(PID (?<pid>\d+)\)') { throw 'Supervisor log identity missing. Nothing stopped.' }
$paperSupervisorPid = [int]$Matches.pid
$paperSupervisorTime = [datetime]::ParseExact($Matches.time,'yyyy-MM-dd HH:mm:ss',[cultureinfo]::InvariantCulture)
$paperParent = Get-CimInstance Win32_Process -Filter "ProcessId = $paperSupervisorPid"
if (-not $paperParent -or $paperParent.Name -notin @('powershell.exe','pwsh.exe') -or [math]::Abs(($paperParent.CreationDate-$paperSupervisorTime).TotalSeconds) -gt 60) {
    throw 'Supervisor PID/start time do not match this project log. Nothing stopped.'
}
$paperStartLine = (Select-String -LiteralPath $paperLogPath -SimpleMatch 'Starting vwap_executor.py (stdout ->' | Select-Object -Last 1).Line
if ($paperStartLine -notmatch '^\[(?<time>[\d-]+ [\d:]+)\]') { throw 'Executor start record missing. Nothing stopped.' }
$paperWorkerTime = [datetime]::ParseExact($Matches.time,'yyyy-MM-dd HH:mm:ss',[cultureinfo]::InvariantCulture)
if (-not $paperStartLine.Contains((Join-Path $paperProject 'logs\vwap_executor_stdout_'))) { throw 'Executor start log belongs to another directory. Nothing stopped.' }
$paperProcesses = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object {
    $_.ParentProcessId -eq $paperSupervisorPid -and [math]::Abs(($_.CreationDate-$paperWorkerTime).TotalSeconds) -le 60
})
if ($paperProcesses.Count -ne 1) { throw "Expected one worker matching supervisor and start time; found $($paperProcesses.Count). Nothing stopped." }
$paperProcess = $paperProcesses[0]
if (-not (Select-String -LiteralPath $paperExecutorPath -SimpleMatch 'def _dead_mans_switch_tick(' -Quiet)) {
    throw 'Patched watchdog source not found. Nothing stopped.'
}
Write-Output "Confirmed executor PID=$($paperProcess.ProcessId), supervisor PID=$paperSupervisorPid, worker start=$($paperProcess.CreationDate.ToString('o'))"
if ($DryRun) { Write-Output 'Dry run verified; nothing stopped.'; return }
Stop-Process -Id $paperProcess.ProcessId -Force -ErrorAction Stop
Write-Output "Old executor stopped; checking supervisor restart for up to $WaitSeconds seconds."
$paperTimer = [diagnostics.stopwatch]::StartNew()
while ($paperTimer.Elapsed.TotalSeconds -lt $WaitSeconds) {
    Start-Sleep -Seconds 1
    $paperNewWorkers = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object {
        $_.ParentProcessId -eq $paperSupervisorPid -and $_.ProcessId -ne $paperProcess.ProcessId -and $_.CreationDate -gt $paperProcess.CreationDate
    })
    $paperStdout = Get-ChildItem (Join-Path $paperProject 'logs') -Filter 'vwap_executor_stdout_*.log' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $paperRuntimeVerified = $true
    if ($ExpectedMarker -like 'VWAP reliability:*') {
        $paperHeartbeat = Get-Item -LiteralPath (Join-Path $paperProject 'logs\vwap_executor_heartbeat.txt') -ErrorAction SilentlyContinue
        $paperRuntimeVerified = $paperNewWorkers.Count -eq 1 -and $null -ne $paperHeartbeat -and
            $paperHeartbeat.LastWriteTime -gt $paperNewWorkers[0].CreationDate -and
            ((Get-Date) - $paperHeartbeat.LastWriteTime).TotalSeconds -lt 90 -and
            (Select-String -LiteralPath $paperStdout.FullName -SimpleMatch 'Read-only: True' -Quiet)
    }
    if ($paperNewWorkers.Count -eq 1 -and $paperStdout.LastWriteTime -gt $paperProcess.CreationDate -and
        $paperRuntimeVerified -and (Select-String -LiteralPath $paperStdout.FullName -SimpleMatch $ExpectedMarker -Quiet)) {
        Write-Output "Verified patched executor started: PID=$($paperNewWorkers[0].ProcessId), marker=$ExpectedMarker"
        return
    }
}
throw "Old executor stopped, but patched restart not confirmed within $WaitSeconds seconds. Check supervisor/stdout logs; do not start a duplicate worker."
