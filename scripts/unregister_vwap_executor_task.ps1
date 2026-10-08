<#
.SYNOPSIS
    Removes the ZigZagBot-VwapExecutor scheduled task registered by
    register_vwap_executor_task.ps1. Run this yourself.

.DESCRIPTION
    Only unregisters the Scheduled Task (stops future auto-starts on
    boot). Does NOT stop a currently-running vwap_executor.py process or
    close any open positions - use Telegram's /vwap_executor_off for
    that (it triggers the emergency-stop path: cancels resting orders,
    closes open positions), or stop the running task first
    (Stop-ScheduledTask -TaskName "ZigZagBot-VwapExecutor") if you want
    to kill the supervisor/process immediately too.
#>

$ErrorActionPreference = "Stop"
$TaskName = "ZigZagBot-VwapExecutor"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Host "Задачі '$TaskName' не знайдено - нічого видаляти."
    return
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Задачу '$TaskName' видалено. Автозапуск при старті системи вимкнено."
Write-Host "Якщо процес зараз працює - він продовжить, поки не завершиться сам "
Write-Host "(або зупини вручну через /vwap_executor_off у Telegram, чи Stop-Process)."
