<#
.SYNOPSIS
    Supervisor wrapper for vwap_executor.py (Крок 3.1, unattended
    autostart, 2026-08-22).

.DESCRIPTION
    Launched by Task Scheduler at system startup - NOT meant to be run
    directly by a human (though it's safe to double-click for a manual
    test run; Ctrl+C or closing the window stops it).

    Restarts vwap_executor.py on BOTH failure modes a real unattended
    week can hit:
      - CRASH: the Python process exits (unhandled exception, etc.) -
        the outer while loop below relaunches it.
      - HANG: the process is alive but the Twisted reactor is stuck (a
        real, previously-hit failure mode in this project - a float
        where protobuf expected an int64 caused an indefinite silent
        hang with zero error, zero timeout, earlier in this same
        session). Detected by reading the heartbeat file
        vwap_executor.py's own _mark_poll_completed writes every poll
        cycle; if it goes stale, this force-kills the process so the
        restart logic above picks it up. A plain Task Scheduler
        "restart on failure" setting would NEVER catch this - the
        process never actually exits, it just stops doing anything.

    Task Scheduler's own "restart on failure" setting (see
    scripts/register_vwap_executor_task.ps1) is a SECOND, independent
    safety net in case this wrapper script itself crashes - the two
    layers cover different failure points (this script supervises
    vwap_executor.py; Task Scheduler supervises this script).

.NOTES
    Every restart is logged to logs\vwap_executor_supervisor.log
    (appended, survives across restarts). vwap_executor.py's own
    stdout/stderr go to per-run timestamped files
    (logs\vwap_executor_stdout_<timestamp>.log) so a restart never
    clobbers the previous run's output - useful for diagnosing exactly
    what happened right before a crash or a forced hang-kill.
#>

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

# Adjust if Python gets reinstalled to a different path - confirmed via
# `where python` / `python -c "import sys; print(sys.executable)"` on
# 2026-08-22. Using the full path (not just "python") avoids depending on
# PATH being set up the same way for whatever account Task Scheduler runs
# this as ("Run whether user is logged on or not" can resolve PATH
# differently than an interactive session).
$PythonExe = "C:\Users\Work\AppData\Local\Programs\Python\Python312\python.exe"

$LogsDir = Join-Path $RepoRoot "logs"
$HeartbeatFile = Join-Path $LogsDir "vwap_executor_heartbeat.txt"
$SupervisorLog = Join-Path $LogsDir "vwap_executor_supervisor.log"

# Generous margin over VWAP_EXECUTOR_STALE_POLL_ALERT_SECONDS (90s
# default, config.py) - the in-process Telegram alert fires first at the
# configured threshold; this is the last-resort automatic action for
# when nobody's there to act on that alert for a while.
$StaleThresholdSeconds = 300
$CheckIntervalSeconds = 30
$RestartDelaySeconds = 15

New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

function Write-SupervisorLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $SupervisorLog -Value "[$timestamp] $Message" -Encoding UTF8
}

Write-SupervisorLog "=== Supervisor started (PID $PID) ==="

while ($true) {
    # BUG FIX (2026-08-24): the whole loop body used to run under
    # $ErrorActionPreference = "Stop" with no try/catch, so ANY transient
    # error inside it (a locked heartbeat file, a race on $process.StartTime,
    # etc.) would kill this ENTIRE supervisor script - and since it's the
    # thing that's supposed to notice and recover from vwap_executor.py
    # hanging, a supervisor that dies silently leaves a hung process running
    # forever with nobody watching it (hit live 2026-08-24: supervisor log
    # stopped right after a "Starting vwap_executor.py" line, and the
    # process it started sat hung for 7+ hours afterward). Catching here
    # logs the failure and lets the outer while loop try again instead of
    # exiting.
    try {
        $runTimestamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $stdOutLog = Join-Path $LogsDir "vwap_executor_stdout_$runTimestamp.log"
        $stdErrLog = Join-Path $LogsDir "vwap_executor_stderr_$runTimestamp.log"

        Write-SupervisorLog "Starting vwap_executor.py (stdout -> $stdOutLog)"

        $process = Start-Process -FilePath $PythonExe -ArgumentList "-u", "vwap_executor.py" `
            -WorkingDirectory $RepoRoot -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $stdOutLog -RedirectStandardError $stdErrLog

        $killedForHang = $false

        while (-not $process.HasExited) {
            Start-Sleep -Seconds $CheckIntervalSeconds

            if ($process.HasExited) {
                break
            }

            if (Test-Path $HeartbeatFile) {
                $lastWriteUtc = (Get-Item $HeartbeatFile).LastWriteTimeUtc
                $processStartUtc = $process.StartTime.ToUniversalTime()
                # BUG FIX (2026-08-24): a heartbeat file left over from BEFORE
                # this process started is not evidence of a hang - it just
                # means this fresh process hasn't had time yet for its first
                # poll cycle (VWAP_EXECUTOR_POLL_SECONDS, 60s default) to
                # write one. Measuring age against the file's mtime alone made
                # every restart get killed within one $CheckIntervalSeconds
                # (30s) of starting, forever, because 30s < 60s is not enough
                # time to ever produce a fresh write - a real crash-loop hit
                # live after a reboot with a stale leftover file on disk.
                # Using whichever is more recent (file mtime vs process start)
                # as the reference point gives every fresh process the full
                # $StaleThresholdSeconds to produce its own first heartbeat,
                # while still catching a genuine in-process hang (heartbeat
                # updates then stops) via the file mtime once it has real data.
                $referenceUtc = if ($lastWriteUtc -gt $processStartUtc) { $lastWriteUtc } else { $processStartUtc }
                $ageSeconds = [int]((Get-Date).ToUniversalTime() - $referenceUtc).TotalSeconds

                if ($ageSeconds -gt $StaleThresholdSeconds) {
                    Write-SupervisorLog "Heartbeat stale (${ageSeconds}s, threshold ${StaleThresholdSeconds}s) - killing hung process (PID $($process.Id))"
                    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
                    $killedForHang = $true
                    break
                }
            }
            # No heartbeat file yet is normal right after a fresh start (the
            # process hasn't completed its first poll cycle) or if it's
            # currently outside a trading session (see vwap_executor.py's
            # _poll_all_symbols - it still marks poll-completed off-session,
            # specifically so this check doesn't misfire every night).
        }

        if ($killedForHang) {
            $reason = "hang (stale heartbeat)"
            $exitCode = "n/a (force-killed)"
        } else {
            $reason = "process exited on its own"
            $exitCode = $process.ExitCode
        }
        Write-SupervisorLog "vwap_executor.py stopped ($reason, exit code=$exitCode) - restarting in ${RestartDelaySeconds}s"
    } catch {
        Write-SupervisorLog "Supervisor loop error: $($_.Exception.Message) - retrying in ${RestartDelaySeconds}s"
    }

    Start-Sleep -Seconds $RestartDelaySeconds
}
