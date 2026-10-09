param([switch]$DryRun)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd('\')
if ($projectRoot -ne 'C:\Users\Work\Desktop\zigzag_bot') { throw 'Unexpected workspace.' }
$resultPath = Join-Path $projectRoot 'logs\vwap_stop_result.json'
try {
    $principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Administrator rights required for SYSTEM executor.'
    }
    $readonly = @(Select-String -LiteralPath (Join-Path $projectRoot '.env') -Pattern '^\s*VWAP_EXECUTOR_READ_ONLY\s*=')
    if ($readonly.Count -ne 1 -or $readonly[0].Line.Split('=',2)[1].Split('#',2)[0].Trim().Trim('"').Trim("'").ToLowerInvariant() -notin @('true','1','yes','on')) {
        throw 'READ_ONLY=true required. No processes stopped.'
    }
    $taskName = 'ZigZagBot-VwapExecutor'
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
    $actions = ($task.Actions | ForEach-Object { $_.Arguments }) -join ' '
    if ($actions -notlike "*$projectRoot*run_vwap_executor.ps1*") {
        throw 'Scheduled task does not match this project supervisor.'
    }
    $line = (Select-String -LiteralPath (Join-Path $projectRoot 'logs\vwap_executor_supervisor.log') -Pattern 'Supervisor started \(PID \d+\)' | Select-Object -Last 1).Line
    if ($line -notmatch '^\[(?<started>[\d-]+ [\d:]+)\].*Supervisor started \(PID (?<supervisor>\d+)\)') {
        throw 'Supervisor identity missing.'
    }
    $supervisorId = [int]$Matches.supervisor
    $started = [datetime]::ParseExact($Matches.started,'yyyy-MM-dd HH:mm:ss',[cultureinfo]::InvariantCulture)
    $supervisor = Get-CimInstance Win32_Process -Filter "ProcessId = $supervisorId"
    $workers = @()
    if ($supervisor) {
        if ($supervisor.Name -notin @('powershell.exe','pwsh.exe') -or
            [math]::Abs(($supervisor.CreationDate-$started).TotalSeconds) -gt 60 -or
            $supervisor.CommandLine -notlike "*$projectRoot*run_vwap_executor.ps1*") {
            throw 'Supervisor identity mismatch. Nothing stopped.'
        }
        $workers = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $supervisorId" |
            Where-Object { $_.Name -in @('python.exe','pythonw.exe') -and $_.CommandLine -match 'vwap_executor\.py' })
    }
    if ($DryRun) {
        Write-Output "Confirmed VWAP task, supervisor=$supervisorId, workers=$($workers.Count). Nothing stopped."
        return
    }
    # Disable first so Task Scheduler cannot recreate the supervisor.
    Disable-ScheduledTask -TaskName $taskName | Out-Null
    Stop-ScheduledTask -TaskName $taskName
    foreach ($process in @($supervisor) + $workers) {
        if (-not $process) { continue }
        $current = Get-CimInstance Win32_Process -Filter "ProcessId = $($process.ProcessId)"
        if ($current -and $current.CreationDate -eq $process.CreationDate) {
            Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
        }
    }
    Start-Sleep -Seconds 3
    $remaining = @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -in @('python.exe','pythonw.exe','powershell.exe','pwsh.exe') -and
        ($_.CommandLine -like "*$projectRoot*run_vwap_executor.ps1*" -or
         ($_.Name -in @('python.exe','pythonw.exe') -and $_.ParentProcessId -eq $supervisorId -and $_.CommandLine -match 'vwap_executor\.py'))
    })
    if ((Get-ScheduledTask -TaskName $taskName).State -ne 'Disabled' -or $remaining.Count -ne 0) {
        throw 'Shutdown verification failed.'
    }
    [pscustomobject]@{success=$true; stoppedUtc=(Get-Date).ToUniversalTime().ToString('o');
        taskDisabled=$true; supervisor=$supervisorId; workers=@($workers | ForEach-Object {$_.ProcessId})} |
        ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
} catch {
    [pscustomobject]@{success=$false; error=$_.Exception.Message} |
        ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
    exit 1
}
